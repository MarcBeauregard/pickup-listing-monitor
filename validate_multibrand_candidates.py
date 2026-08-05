#!/usr/bin/env python3
"""Valide et documente le lot multimarque sans ingestion aveugle."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from monitor import fetch_listing
from scan_deals import canonical_url, monthly_payment_exact


GROUPS = ("admissibles", "non_confirmes", "rejetes")
REQUIRED = (
    "url", "marque", "modele", "cabine", "annee", "km", "prix",
    "mensualite_calculee", "vendeur", "ville", "distance_estimee_km", "statut",
)


def flatten(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(group, row) for group in GROUPS for row in payload.get(group, [])]


def explicit_tacoma_double_cab(row: dict[str, Any]) -> bool:
    proof = str(row.get("preuve_cabine") or "").lower()
    return (
        row.get("marque") == "Toyota"
        and row.get("modele") == "Tacoma"
        and "double cab" in proof
        and "absent" not in proof
        and "indirect" not in proof
    )


def validate_row(
    source_group: str,
    row: dict[str, Any],
    live: dict[str, Any] | None,
    existing_urls: set[str],
    duplicate_urls: set[str],
) -> dict[str, Any]:
    missing = [field for field in REQUIRED if field not in row or row[field] is None]
    url = canonical_url(str(row.get("url") or ""))
    result = {
        "url": url,
        "source_group": source_group,
        "source_status": row.get("statut"),
        "seller": row.get("vendeur"),
        "make": "Ram" if str(row.get("marque") or "").lower() == "ram" else row.get("marque"),
        "model": row.get("modele"),
        "missing_fields": missing,
        "duplicate_with_existing": url in existing_urls,
        "duplicate_in_batch": url in duplicate_urls,
        "supplied": {
            "year": row.get("annee"), "mileage": row.get("km"), "price": row.get("prix"),
            "monthly": row.get("mensualite_calculee"), "distance_km": row.get("distance_estimee_km"),
        },
        "tacoma_double_cab_explicit": explicit_tacoma_double_cab(row),
    }
    if missing or not url.startswith("https://") or url in existing_urls or url in duplicate_urls:
        result.update({"decision": "rejected_validation", "reason": "schéma, URL ou unicité invalide"})
        return result
    if source_group == "non_confirmes":
        result.update({"decision": "distance_unconfirmed", "reason": row["motif"]})
        return result
    if source_group == "rejetes":
        result.update({"decision": "rejected_initial", "reason": row["motif"]})
        return result
    current = live or {}
    if current.get("status") == "fetch_error":
        result.update({"decision": "live_check_failed", "reason": "vérification réseau non concluante", "live": current})
        return result
    if current.get("status") != "active":
        result.update({"decision": "rejected_inactive", "reason": "annonce inactive ou illisible", "live": current})
        return result
    year = current.get("year") if current.get("year") is not None else row["annee"]
    mileage = current.get("mileage") if current.get("mileage") is not None else row["km"]
    price = current.get("price") if current.get("price") is not None else row["prix"]
    monthly = monthly_payment_exact(price)
    distance = row["distance_estimee_km"]
    result["validated"] = {
        "year": year, "mileage": mileage, "price": price, "monthly": monthly,
        "distance_km": distance, "distance_band": "0-150" if distance <= 150 else "151-250",
    }
    result["corrections"] = {
        "payment": monthly != row["mensualite_calculee"],
        "live_price": price != row["prix"],
        "live_mileage": mileage != row["km"],
        "make_case": row["marque"] != result["make"],
        "cab": "unknown" if row.get("marque") == "Toyota" and row.get("modele") == "Tacoma" and not explicit_tacoma_double_cab(row) else None,
    }
    if year < 2017 or distance > 250 or not 500 <= monthly <= 700:
        result.update({"decision": "rejected_validation", "reason": "année, rayon ou budget hors contrat"})
    elif mileage > 120_000:
        result.update({"decision": "high_mileage", "reason": "kilométrage supérieur à 120 000 km; hors classement principal"})
    else:
        result.update({"decision": "eligible", "reason": "contrôles année, rayon, budget, URL et kilométrage réussis"})
    return result


def validate(
    payload: dict[str, Any],
    existing_urls: set[str],
    live_by_url: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = flatten(payload)
    counts: dict[str, int] = {}
    seen: set[str] = set()
    duplicate_urls: set[str] = set()
    for _group, row in rows:
        url = canonical_url(str(row.get("url") or ""))
        if url in seen:
            duplicate_urls.add(url)
        seen.add(url)
    report_rows = [
        validate_row(group, row, live_by_url.get(canonical_url(row.get("url", ""))), existing_urls, duplicate_urls)
        for group, row in rows
    ]
    for row in report_rows:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
    return {
        "schema_version": 1,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "source_counts": {group: len(payload.get(group, [])) for group in GROUPS},
        "total": len(rows),
        "decision_counts": counts,
        "rows": report_rows,
    }


def markdown(report: dict[str, Any]) -> str:
    payment_corrections = sum(row.get("corrections", {}).get("payment", False) for row in report["rows"])
    live_price_corrections = sum(row.get("corrections", {}).get("live_price", False) for row in report["rows"])
    live_mileage_corrections = sum(row.get("corrections", {}).get("live_mileage", False) for row in report["rows"])
    make_corrections = sum(row.get("corrections", {}).get("make_case", False) for row in report["rows"])
    duplicates = sum(row["duplicate_with_existing"] or row["duplicate_in_batch"] for row in report["rows"])
    lines = [
        "# Validation stricte du lot multimarque — 2026-08-05",
        "",
        f"Validation : `{report['validated_at']}`",
        "",
        f"Source : {report['total']} lignes; décisions : `{json.dumps(report['decision_counts'], ensure_ascii=False, sort_keys=True)}`.",
        "",
        f"Décompte livré : `{json.dumps(report['source_counts'], ensure_ascii=False, sort_keys=True)}`. Doublons internes ou avec les 20 annonces existantes : **{duplicates}**.",
        "",
        f"Corrections appliquées : {payment_corrections} mensualités actives recalculées à deux décimales, {live_price_corrections} prix live, {live_mileage_corrections} kilométrage live et {make_corrections} casse de marque.",
        "",
        "Les cinq distances non confirmées ne sont pas ingérées. Les lignes `high_mileage` restent consultables par un filtre désactivé par défaut et sont exclues des alertes, du podium et du compte admissible.",
        "",
        "Le rapport porte uniquement sur le lot livré. Le tableau de bord fusionne ce lot avec les annonces découvertes lors du scan live et publie des compteurs `batch_*` et `source_*` séparés.",
        "",
        "| # | Décision | Véhicule | Valeurs validées | URL |",
        "|---:|---|---|---|---|",
    ]
    for index, row in enumerate(report["rows"], 1):
        values = row.get("validated") or row.get("supplied") or {}
        vehicle = f"{row.get('make') or '—'} {row.get('model') or '—'}"
        proof = f"{values.get('year', '—')} · {values.get('mileage', '—')} km · {values.get('price', '—')} $ · {values.get('monthly', '—')} $/mois"
        lines.append(f"| {index} | {row['decision']} | {vehicle} | {proof} | [annonce]({row['url']}) |")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/multibrand_candidates_2026-08-05.json"))
    parser.add_argument("--existing", type=Path, default=Path("docs/data/deals.json"))
    parser.add_argument("--output", type=Path, default=Path("data/multibrand_validation_2026-08-05.json"))
    parser.add_argument("--report", type=Path, default=Path("docs/MULTIBRAND_VALIDATION_2026-08-05.md"))
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=float, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    existing = json.loads(args.existing.read_text(encoding="utf-8")) if args.existing.exists() else {"deals": []}
    existing_urls = {canonical_url(item["url"]) for item in existing.get("deals", [])}
    live_by_url: dict[str, dict[str, Any]] = {}
    if args.live:
        urls = [canonical_url(row["url"]) for row in payload.get("admissibles", [])]
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(fetch_listing, url, args.timeout): url for url in urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    live_by_url[url] = future.result()
                except Exception as exc:
                    live_by_url[url] = {"status": "fetch_error", "error": str(exc)}
    report = validate(payload, existing_urls, live_by_url)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"total": report["total"], **report["decision_counts"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
