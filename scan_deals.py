#!/usr/bin/env python3
"""Découvre et publie des deals de pickups pour le tableau statique."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from monitor import USER_AGENT, fetch_listing
from trust_score import trust_score as calculate_trust_score


TAX_RATE = 0.14975
UNKNOWN_ENRICHMENT = {"status": "unconfirmed"}
NO_LEGAL_SIGNAL = {"status": "not_audited"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_html(url: str, timeout: float) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fr-CA,fr;q=0.9,en;q=0.7",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def discover_urls(document: str, source: dict[str, Any]) -> list[str]:
    domain = source.get("listing_domain", "www.autohebdo.net")
    listing_path = source.get("listing_path_pattern", r"/annonces/[^\"'<>\s]+")
    absolute = re.findall(rf'https?://{re.escape(domain)}{listing_path}', document, flags=re.IGNORECASE)
    relative = re.findall(rf'["\']({listing_path})', document, flags=re.IGNORECASE)
    candidates = [unescape(url).rstrip("/,") for url in absolute]
    base_url = source.get("base_url", f"https://{domain}")
    candidates.extend(urljoin(base_url, unescape(url).rstrip("/,")) for url in relative)
    unique = []
    seen = set()
    for url in candidates:
        parts = urlsplit(url)
        canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
        if canonical not in seen:
            seen.add(canonical)
            unique.append(canonical)
    return unique[: int(source.get("max_listings", 30))]


def monthly_payment(price: int, annual_rate: float = 0.07, months: int = 84) -> int:
    principal = price * (1 + TAX_RATE)
    monthly_rate = annual_rate / 12
    payment = principal * monthly_rate / (1 - (1 + monthly_rate) ** -months)
    return round(payment)


def monthly_payment_exact(price: int, annual_rate: float = 0.07, months: int = 84) -> float:
    """Recalcule la mensualité contractuelle à deux décimales."""
    principal = price * (1 + TAX_RATE)
    monthly_rate = annual_rate / 12
    payment = principal * monthly_rate / (1 - (1 + monthly_rate) ** -months)
    return round(payment, 2)


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def candidate_rows(candidates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Retourne seulement les lignes livrées comme admissibles; les 5 distances non confirmées restent exclues."""
    return {canonical_url(item["url"]): item for item in candidates.get("admissibles", [])}


def candidate_cab(row: dict[str, Any]) -> tuple[str | None, str]:
    cab = str(row.get("cabine") or "").strip()
    proof = str(row.get("preuve_cabine") or "").lower()
    make = str(row.get("marque") or "").lower()
    model = str(row.get("modele") or "").lower()
    if make == "toyota" and model == "tacoma":
        if "double cab" in proof and "absent" not in proof and "indirect" not in proof:
            return "Double Cab", "double_cab"
        return None, "unknown"
    normalized = f"{cab} {proof}".lower()
    if "double cab" in normalized or "crew cab" in normalized or "supercrew" in normalized or "cabine double" in normalized:
        return cab or "Crew Cab", "crew_cab"
    if "access cab" in normalized:
        return "Access Cab", "access_cab"
    return cab or None, "unknown"


def merge_candidate_metadata(current: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    """Complète uniquement les métadonnées explicites de la fiche candidate; le prix/km live prévaut."""
    if not row:
        return current
    result = dict(current)
    make = str(row.get("marque") or "").strip()
    if make.lower() == "ram":
        make = "Ram"
    cab, cab_class = candidate_cab(row)
    fallbacks = {
        "make": make or None,
        "model": row.get("modele"),
        "engine": row.get("moteur"),
        "transmission": row.get("transmission"),
        "drivetrain": row.get("rouage"),
        "location": row.get("ville"),
    }
    for field, value in fallbacks.items():
        if not result.get(field) and value:
            result[field] = value
    if make == "Toyota" and row.get("modele") == "Tacoma":
        result["cab"] = cab
        result["cab_class"] = cab_class
    elif result.get("cab_class", "unknown") == "unknown" and cab:
        result["cab"] = cab
        result["cab_class"] = cab_class
    distance = row.get("distance_estimee_km")
    result.update({
        "seller_name": row.get("vendeur"),
        "distance_km": distance,
        "distance_band": "0-150" if isinstance(distance, (int, float)) and distance <= 150 else "151-250",
        "cab_proof": row.get("preuve_cabine"),
        "candidate_source_status": row.get("statut"),
    })
    return result


def is_high_mileage_only(current: dict[str, Any], criteria: dict[str, Any]) -> bool:
    mileage = current.get("mileage")
    if not isinstance(mileage, int) or mileage <= criteria["max_mileage"]:
        return False
    relaxed = {**criteria, "max_mileage": mileage}
    return evaluate(current, relaxed)[0]


def evaluate(current: dict[str, Any], criteria: dict[str, Any]) -> tuple[bool, list[str], int]:
    reasons = []
    score = 100
    price = current.get("price")
    year = current.get("year")
    mileage = current.get("mileage")
    if current.get("status") != "active":
        reasons.append("annonce inactive ou illisible")
        score -= 100
    if price is None or price > criteria["max_price"]:
        reasons.append("prix hors cible ou inconnu")
        score -= 35
    elif criteria.get("min_monthly") and monthly_payment(price) < criteria["min_monthly"]:
        reasons.append("paiement estimé sous la fourchette")
        score -= 10
    elif criteria.get("max_monthly") and monthly_payment(price) > criteria["max_monthly"]:
        reasons.append("paiement estimé au-dessus de la fourchette")
        score -= 35
    if year is None or year < criteria["min_year"]:
        reasons.append("année hors cible ou inconnue")
        score -= 20
    if mileage is None:
        reasons.append("kilométrage inconnu")
        score -= 15
    elif mileage > criteria["max_mileage"]:
        reasons.append("kilométrage au-dessus de la cible")
        score -= 25
    eligible = not reasons
    if eligible:
        if current.get("trim") == "Lariat":
            score += 15
        if mileage is not None and mileage <= 100_000:
            score += 10
        if price is not None and monthly_payment(price) <= 700:
            score += 5
        priority = criteria.get("priority", {})
        if priority and all(current.get(field) == priority.get(field) for field in ("make", "model", "cab_class")):
            score += int(priority.get("score_bonus", 0))
    return eligible, reasons, max(score, 0)


def deal_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def unconfirmed(value: dict[str, Any] | None = None, *, mechanical_mismatch: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = dict(UNKNOWN_ENRICHMENT)
    if value:
        if isinstance(value.get("name"), str) and value["name"].strip():
            result["name"] = value["name"].strip()
        if isinstance(value.get("reason"), str) and value["reason"].strip():
            result["reason"] = value["reason"].strip()
    if mechanical_mismatch and "reason" not in result:
        result["reason"] = "configuration mécanique non concordante"
    return result


def normalized_mechanical(field: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    if field == "transmission" and ("automatic" in normalized or "automatique" in normalized or "as10" in normalized):
        return "automatic"
    if field == "drivetrain" and ("4wd" in normalized or "4x4" in normalized or "4rm" in normalized):
        return "4WD"
    return value.strip()


def enrichment_for(url: str, current: dict[str, Any], enrichments: dict[str, Any]) -> dict[str, Any]:
    """Retourne uniquement un enrichissement dont l'annonce et la mécanique concordent exactement."""
    entry = next((item for item in enrichments.get("listings", []) if item.get("url") == url), None)
    if not entry:
        return {"seller_reputation": unconfirmed(), "fuel_economy": unconfirmed()}

    seller = entry.get("seller_reputation") or UNKNOWN_ENRICHMENT
    fuel = entry.get("fuel_economy") or UNKNOWN_ENRICHMENT
    seller_fields = ("name", "rating", "review_count", "source_url", "verified_at")
    seller_confirmed = (
        seller.get("status") == "confirmed"
        and all(seller.get(field) is not None for field in seller_fields)
        and isinstance(seller.get("rating"), (int, float))
        and 0 <= seller["rating"] <= 5
        and isinstance(seller.get("review_count"), int)
        and seller["review_count"] >= 0
        and str(seller.get("source_url", "")).startswith("https://")
    )
    required = fuel.get("match", {})
    mechanical_fields = ("year", "engine", "transmission", "drivetrain")
    fuel_fields = ("city_l_per_100km", "highway_l_per_100km", "source_url", "verified_at")
    exact_match = (
        fuel.get("status") == "confirmed"
        and all(fuel.get(field) is not None for field in fuel_fields)
        and all(isinstance(fuel.get(field), (int, float)) and 0 < fuel[field] < 100 for field in ("city_l_per_100km", "highway_l_per_100km"))
        and str(fuel.get("source_url", "")).startswith("https://")
        and all(
            required.get(field) is not None
            and normalized_mechanical(field, required.get(field)) == normalized_mechanical(field, current.get(field))
            for field in mechanical_fields
        )
    )
    return {
        "seller_reputation": seller if seller_confirmed else unconfirmed(seller),
        "fuel_economy": fuel if exact_match else unconfirmed(fuel, mechanical_mismatch=fuel.get("status") == "confirmed"),
    }


def legal_signal_for(url: str, signals: dict[str, Any]) -> dict[str, Any]:
    """Associe un signal à une URL exacte, jamais au seul nom commercial."""
    entry = next((item for item in signals.get("listings", []) if item.get("url") == url), None)
    if not entry:
        return {**NO_LEGAL_SIGNAL, "source_checked_at": signals.get("checked_at")}
    required = (
        "status", "nature", "event_type", "event_date", "legal_entity", "permit_or_neq",
        "branch", "source_url", "source_checked_at", "match_status", "match_basis", "branch_matched",
    )
    if not all(entry.get(field) is not None for field in required) or not str(entry["source_url"]).startswith("https://"):
        return {**NO_LEGAL_SIGNAL, "source_checked_at": signals.get("checked_at")}
    exact = entry["match_status"] == "exact" and entry["branch_matched"] is True
    different = entry["match_status"] == "different_entity" and entry["branch_matched"] is False
    if (entry["status"] in {"red", "yellow"} and exact) or (entry["status"] == "unattributed" and different):
        return {key: value for key, value in entry.items() if key not in {"url", "case_id"}}
    return {**NO_LEGAL_SIGNAL, "source_checked_at": signals.get("checked_at")}


def mapped_legal_signal_for(url: str, mapping: dict[str, Any]) -> dict[str, Any] | None:
    """Adapte le mapping juridique vérifié sans effacer la portée exacte de la succursale."""
    entry = next((item for item in mapping.get("entries", []) if canonical_url(item.get("url", "")) == canonical_url(url)), None)
    if not entry:
        return None
    if entry.get("entity_match") != "exact" or entry.get("applicable") is not True:
        return None
    if entry.get("severity") not in {"red", "yellow"}:
        return None
    branch_scope = entry.get("branch_match")
    if branch_scope not in {"exact_event_branch", "exact_trade_name_and_city", "entity_only_branch_not_named_in_event", "entity_head_office_not_named_in_event"}:
        return None
    seller = str(entry.get("seller") or "").lower()
    sources = mapping.get("sources", {})
    if "automobile en direct" in seller:
        source_url = sources.get("automobile_en_direct_conviction")
    elif "hgr" in seller or "grégoire" in seller:
        source_url = sources.get("hgregoire_settlement")
    elif "honda st-basile" in seller:
        source_url = sources.get("honda_st_basile_conviction")
    else:
        source_url = sources.get("centre_bd_judgment_report")
    if not str(source_url or "").startswith("https://"):
        return None
    return {
        "status": entry["severity"],
        "nature": entry["display_note"],
        "event_type": entry["event_type"],
        "event_date": entry["event_date"],
        "legal_entity": entry["legal_entity"],
        "permit_or_neq": entry["permit"],
        "branch": entry["branch"],
        "source_url": source_url,
        "source_checked_at": mapping.get("generated_at"),
        "match_status": "exact",
        "match_basis": "raison sociale ou permis concordant",
        "branch_matched": branch_scope in {"exact_event_branch", "exact_trade_name_and_city"},
        "branch_scope": branch_scope,
        "entity_match": "exact",
        "applicable": True,
    }


def compute_trust_score(
    seller: dict[str, Any],
    legal: dict[str, Any],
    computed_at: str,
) -> dict[str, Any]:
    """Adapte l'implémentation de référence Denise au schéma explicable du dashboard."""
    legal_status = {
        "red": "rouge",
        "yellow": "jaune",
        "unattributed": "vigilance_homonymie",
        "none_confirmed": "aucun_signal_audité",
        "not_audited": "non_audité",
    }.get(legal.get("status"), "non_audité")
    labels = {
        "rouge": "🔴 Risque élevé",
        "jaune": "🟡 Prudence",
        "vigilance_homonymie": "🟠 Vigilance — homonymie, aucune faute prouvée contre ce vendeur",
        "aucun_signal_audité": "⚪ Aucun signal confirmé dans les sources auditées",
        "non_audité": "⚪ Non audité juridiquement",
    }
    rating = seller.get("rating")
    review_count = seller.get("review_count")
    confirmed = (
        seller.get("status") == "confirmed"
        and isinstance(rating, (int, float))
        and 0 <= rating <= 5
        and isinstance(review_count, int)
        and review_count >= 0
    )
    reference = calculate_trust_score(
        rating=rating if confirmed else None,
        review_count=review_count if confirmed else None,
        identity_confirmed=confirmed,
        reputation_confirmed=confirmed,
        legal_status=legal_status,
        verified_at=seller.get("verified_at"),
        computed_at=computed_at,
    )
    components = reference["components"]
    missing_floor = reference["floor_applied_missing_data"]
    label = labels[legal_status] if reference["score"] is not None else "⚪ Données insuffisantes"

    reasons = []
    if legal.get("nature"):
        reasons.append(legal["nature"])
    if legal_status == "non_audité":
        reasons.append("Aucune recherche juridique spécifique confirmée; plafond de 80 appliqué.")
    if missing_floor:
        reasons.append("Réputation Google insuffisante; plancher juridique appliqué sans estimation.")
    if components["date_invalid_or_missing"] and confirmed:
        reasons.append("Date de réputation manquante, future ou invalide; fraîcheur minimale de 0,5 appliquée.")
    sources = list(dict.fromkeys(
        value for value in (seller.get("source_url"), legal.get("source_url")) if value
    ))
    return {
        "score": reference["score"],
        "level": legal_status,
        "level_label": label,
        "components": {
            "reputation_base": components["reputation_base_effective"],
            **components,
            "band_applied": reference["band"],
            "missing_data_floor_applied": missing_floor,
        },
        "legal_status": legal_status,
        "reasons": reasons,
        "sources": sources,
        "computed_at": computed_at,
        "formula_version": 1,
    }


def scan(
    config: dict[str, Any],
    previous: dict[str, Any] | None,
    timeout: float,
    source_fetcher: Callable[[str, float], str] = fetch_html,
    listing_fetcher: Callable[[str, float], dict[str, Any]] = fetch_listing,
    enrichments: dict[str, Any] | None = None,
    legal_signals: dict[str, Any] | None = None,
    candidates: dict[str, Any] | None = None,
    legal_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    discovered = []
    source_errors = []
    for source in config["sources"]:
        try:
            page = source_fetcher(source["url"], timeout)
            source_urls = discover_urls(page, source)
            if not source_urls:
                source_errors.append({"source": source["name"], "error": "aucune annonce découverte; structure possiblement changée"})
            discovered.extend(source_urls)
        except Exception as exc:  # la source doit être isolée du reste du scan
            source_errors.append({"source": source["name"], "error": str(exc)})

    candidates_by_url = candidate_rows(candidates or {})
    discovered.extend(candidates_by_url)
    urls = list(dict.fromkeys(discovered))
    fetched: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, max(len(urls), 1))) as executor:
        futures = {executor.submit(listing_fetcher, url, timeout): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                fetched[url] = future.result()
            except Exception as exc:
                fetched[url] = {"status": "fetch_error", "price": None, "error": str(exc)}

    previous_deals = {deal["id"]: deal for deal in (previous or {}).get("deals", [])}
    checked_at = utc_now()
    checked_datetime = datetime.fromisoformat(checked_at)
    deals = []
    for url in urls:
        candidate = candidates_by_url.get(canonical_url(url))
        current = merge_candidate_metadata(fetched[url], candidate)
        eligible, reasons, score = evaluate(current, config["criteria"])
        high_mileage = is_high_mileage_only(current, config["criteria"])
        if high_mileage:
            reasons = ["kilométrage élevé — hors classement principal"]
        identifier = deal_id(url)
        price = current.get("price")
        previous_deal = previous_deals.get(identifier, {})
        enrichment = enrichment_for(url, current, enrichments or {})
        if enrichment["seller_reputation"].get("status") != "confirmed" and current.get("seller_name"):
            enrichment["seller_reputation"] = unconfirmed({"name": current["seller_name"]})
        legal_signal = mapped_legal_signal_for(url, legal_mapping or {}) or legal_signal_for(url, legal_signals or {})
        trust_score = compute_trust_score(enrichment["seller_reputation"], legal_signal, checked_at[:10])
        first_seen_at = previous_deal.get("first_seen_at") or checked_at
        try:
            recent = checked_datetime - datetime.fromisoformat(first_seen_at) <= timedelta(hours=72)
        except ValueError:
            first_seen_at = checked_at
            recent = True
        deals.append(
            {
                "id": identifier,
                "title": current.get("title") or "Pickup — détails à confirmer",
                "url": url,
                "image": current.get("image"),
                "price": price,
                "monthly_7pct": monthly_payment(price) if price else None,
                "year": current.get("year"),
                "mileage": current.get("mileage"),
                "engine": current.get("engine"),
                "trim": current.get("trim"),
                "cab": current.get("cab"),
                "cab_class": current.get("cab_class", "unknown"),
                "make": current.get("make"),
                "model": current.get("model"),
                "transmission": current.get("transmission"),
                "drivetrain": current.get("drivetrain"),
                "location": current.get("location"),
                "seller_name": current.get("seller_name"),
                "distance_km": current.get("distance_km"),
                "distance_band": current.get("distance_band"),
                "cab_proof": current.get("cab_proof"),
                **enrichment,
                "seller_legal_signal": legal_signal,
                "trust_score": trust_score,
                "status": current.get("status"),
                "eligible": eligible,
                "high_mileage": high_mileage,
                "alert_eligible": eligible and not high_mileage,
                "candidate_status": "eligible" if eligible else "high_mileage" if high_mileage else "rejected",
                "score": score,
                "reasons": reasons,
                "first_seen_at": first_seen_at,
                "is_new": recent,
                "new_in_run": identifier not in previous_deals,
                "checked_at": checked_at,
            }
        )
    deals.sort(key=lambda item: (not item["eligible"], not item["high_mileage"], -item["score"], item["price"] or 999_999))
    return {
        "schema_version": 2,
        "last_checked_at": checked_at,
        "scan_status": "ok" if not source_errors else "partial",
        "source_errors": source_errors,
        "criteria": config["criteria"],
        "counts": {
            "discovered": len(deals),
            "eligible": sum(deal["eligible"] for deal in deals),
            "high_mileage": sum(deal["high_mileage"] for deal in deals),
            "new": sum(deal["is_new"] for deal in deals),
            "new_eligible": sum(deal["is_new"] and deal["eligible"] for deal in deals),
            "new_in_run": sum(deal["new_in_run"] for deal in deals),
        },
        "deals": deals,
    }


def update_history(previous_history: list[dict[str, Any]], result: dict[str, Any]) -> list[dict[str, Any]]:
    entry = {
        "checked_at": result["last_checked_at"],
        "status": result["scan_status"],
        "discovered": result["counts"]["discovered"],
        "eligible": result["counts"]["eligible"],
        "new_ids": [deal["id"] for deal in result["deals"] if deal["new_in_run"]],
    }
    return ([entry] + previous_history)[:40]


def load_json(path: Path, fallback: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("data/sources.json"))
    parser.add_argument("--deals", type=Path, default=Path("docs/data/deals.json"))
    parser.add_argument("--history", type=Path, default=Path("docs/data/history.json"))
    parser.add_argument("--enrichments", type=Path, default=Path("data/enrichments.json"))
    parser.add_argument("--legal-signals", type=Path, default=Path("data/seller_legal_signals.json"))
    parser.add_argument("--candidates", type=Path, default=Path("data/multibrand_candidates_2026-08-05.json"))
    parser.add_argument("--legal-mapping", type=Path, default=Path("data/multibrand_legal_mapping_2026-08-05.json"))
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_json(args.config, {})
    previous = load_json(args.deals, None)
    history = load_json(args.history, [])
    enrichments = load_json(args.enrichments, {"schema_version": 1, "listings": []})
    legal_signals = load_json(args.legal_signals, {"schema_version": 1, "listings": []})
    candidates = load_json(args.candidates, {"schema_version": 1, "admissibles": []})
    legal_mapping = load_json(args.legal_mapping, {"schema_version": 1, "entries": []})
    result = scan(
        config,
        previous,
        args.timeout,
        enrichments=enrichments,
        legal_signals=legal_signals,
        candidates=candidates,
        legal_mapping=legal_mapping,
    )
    write_json(args.deals, result)
    write_json(args.history, update_history(history, result))
    print(json.dumps({"status": result["scan_status"], **result["counts"]}, ensure_ascii=False))
    return 0 if result["scan_status"] in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
