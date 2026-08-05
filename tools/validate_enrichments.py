#!/usr/bin/env python3
"""Valide la table d'enrichissement contre le snapshot d'annonces."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monitor import infer_engine


SELLER_FIELDS = ("name", "rating", "review_count", "source_url", "verified_at")
FUEL_FIELDS = ("city_l_per_100km", "highway_l_per_100km", "source_url", "verified_at")
MECHANICAL_FIELDS = ("year", "engine", "transmission", "drivetrain")
LEGAL_FIELDS = (
    "case_id", "url", "status", "nature", "event_type", "event_date", "legal_entity",
    "permit_or_neq", "branch", "source_url", "source_checked_at", "match_status",
    "match_basis", "branch_matched",
)


def valid_date(value: Any) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def validate(snapshot: dict[str, Any], enrichments: dict[str, Any]) -> dict[str, Any]:
    deals = snapshot.get("deals", [])
    listings = enrichments.get("listings", [])
    deal_urls = [deal.get("url") for deal in deals]
    deal_by_url = {deal.get("url"): deal for deal in deals}
    urls = [item.get("url") for item in listings]
    duplicate_snapshot_urls = sorted({url for url in deal_urls if deal_urls.count(url) > 1})
    duplicate_urls = sorted({url for url in urls if urls.count(url) > 1})
    orphan_urls = sorted(url for url in set(urls) if url not in deal_by_url)
    missing_urls = sorted(url for url in deal_by_url if url not in set(urls))
    errors: list[str] = []
    seller_confirmed = 0
    fuel_confirmed = 0
    mechanical_matches = 0

    for index, item in enumerate(listings):
        label = item.get("url") or f"entrée {index}"
        if not isinstance(item.get("url"), str) or not item["url"].startswith("https://"):
            errors.append(f"{label}: URL d'annonce non HTTPS")
        seller = item.get("seller_reputation", {})
        if seller.get("status") not in {"confirmed", "unconfirmed"}:
            errors.append(f"{label}: statut vendeur invalide")
        elif seller.get("status") == "confirmed":
            seller_confirmed += 1
            if not all(seller.get(field) is not None for field in SELLER_FIELDS):
                errors.append(f"{label}: preuve vendeur incomplète")
            if not isinstance(seller.get("rating"), (int, float)) or not 0 <= seller["rating"] <= 5:
                errors.append(f"{label}: note vendeur invalide")
            if not isinstance(seller.get("review_count"), int) or seller["review_count"] < 0:
                errors.append(f"{label}: nombre d'avis invalide")
            if not str(seller.get("source_url", "")).startswith("https://"):
                errors.append(f"{label}: source vendeur non HTTPS")
            if not valid_date(seller.get("verified_at")):
                errors.append(f"{label}: date vendeur invalide")
            elif date.fromisoformat(seller["verified_at"]) > date.today():
                errors.append(f"{label}: date vendeur future")
        elif any(seller.get(field) is not None for field in ("rating", "review_count", "source_url", "verified_at")):
            errors.append(f"{label}: valeur vendeur présente sans confirmation")

        fuel = item.get("fuel_economy", {})
        if fuel.get("status") not in {"confirmed", "unconfirmed"}:
            errors.append(f"{label}: statut consommation invalide")
        elif fuel.get("status") == "confirmed":
            fuel_confirmed += 1
            match = fuel.get("match", {})
            if not all(fuel.get(field) is not None for field in FUEL_FIELDS):
                errors.append(f"{label}: preuve consommation incomplète")
            if not all(isinstance(fuel.get(field), (int, float)) and 0 < fuel[field] < 100 for field in ("city_l_per_100km", "highway_l_per_100km")):
                errors.append(f"{label}: unités L/100 km invalides")
            if not str(fuel.get("source_url", "")).startswith("https://"):
                errors.append(f"{label}: source consommation non HTTPS")
            if not valid_date(fuel.get("verified_at")):
                errors.append(f"{label}: date consommation invalide")
            elif date.fromisoformat(fuel["verified_at"]) > date.today():
                errors.append(f"{label}: date consommation future")
            if not all(match.get(field) is not None for field in MECHANICAL_FIELDS):
                errors.append(f"{label}: correspondance mécanique incomplète")
            deal = deal_by_url.get(label)
            snapshot_engine = deal.get("engine") if deal else None
            if deal and snapshot_engine is None:
                snapshot_engine = infer_engine(" ".join(str(deal.get(field) or "") for field in ("title", "description", "url")))
            if deal and match.get("year") == deal.get("year") and match.get("engine") == snapshot_engine:
                mechanical_matches += 1
            else:
                errors.append(f"{label}: année ou moteur divergent du snapshot")
        elif any(fuel.get(field) is not None for field in (*FUEL_FIELDS, "match")):
            errors.append(f"{label}: valeur de consommation présente sans confirmation")

    return {
        "snapshot_urls": len(deal_by_url),
        "enrichment_urls": len(urls),
        "unique_enrichment_urls": len(set(urls)),
        "duplicate_snapshot_urls": duplicate_snapshot_urls,
        "duplicate_urls": duplicate_urls,
        "orphan_urls": orphan_urls,
        "missing_urls": missing_urls,
        "seller_confirmed": seller_confirmed,
        "fuel_confirmed": fuel_confirmed,
        "mechanical_year_engine_matches": mechanical_matches,
        "errors": errors,
        "valid": not duplicate_snapshot_urls and not duplicate_urls and not orphan_urls and not missing_urls and not errors,
    }


def validate_legal_signals(snapshot: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    snapshot_urls = {deal.get("url") for deal in snapshot.get("deals", [])}
    listings = signals.get("listings", [])
    urls = [item.get("url") for item in listings]
    errors: list[str] = []
    for index, item in enumerate(listings):
        label = item.get("url") or f"entrée {index}"
        if not all(item.get(field) is not None for field in LEGAL_FIELDS):
            errors.append(f"{label}: signal juridique incomplet")
            continue
        if item["url"] not in snapshot_urls:
            errors.append(f"{label}: URL juridique orpheline")
        if not str(item["source_url"]).startswith("https://"):
            errors.append(f"{label}: source juridique non HTTPS")
        for field in ("event_date", "source_checked_at"):
            if not valid_date(item[field]) or date.fromisoformat(item[field]) > date.today():
                errors.append(f"{label}: date juridique invalide")
        exact = item["match_status"] == "exact" and item["branch_matched"] is True
        different = item["match_status"] == "different_entity" and item["branch_matched"] is False
        if item["status"] in {"red", "yellow"} and not exact:
            errors.append(f"{label}: alerte attribuée sans concordance exacte")
        if item["status"] == "unattributed" and not different:
            errors.append(f"{label}: homonymie attribuée à tort")
        if item["status"] not in {"red", "yellow", "unattributed"}:
            errors.append(f"{label}: statut juridique invalide")
    duplicates = sorted({url for url in urls if urls.count(url) > 1})
    return {
        "entries": len(listings),
        "unique_cases": len({item.get("case_id") for item in listings}),
        "red": sum(item.get("status") == "red" for item in listings),
        "yellow": sum(item.get("status") == "yellow" for item in listings),
        "unattributed": sum(item.get("status") == "unattributed" for item in listings),
        "duplicate_urls": duplicates,
        "errors": errors,
        "valid": not duplicates and not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=Path, default=Path("docs/data/deals.json"))
    parser.add_argument("--enrichments", type=Path, default=Path("data/enrichments.json"))
    parser.add_argument("--legal-signals", type=Path, default=Path("data/seller_legal_signals.json"))
    args = parser.parse_args()
    report = validate(
        json.loads(args.deals.read_text(encoding="utf-8")),
        json.loads(args.enrichments.read_text(encoding="utf-8")),
    )
    legal_report = validate_legal_signals(
        json.loads(args.deals.read_text(encoding="utf-8")),
        json.loads(args.legal_signals.read_text(encoding="utf-8")),
    )
    print(json.dumps({"enrichments": report, "legal_signals": legal_report}, ensure_ascii=False, indent=2))
    return 0 if report["valid"] and legal_report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
