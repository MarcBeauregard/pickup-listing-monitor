#!/usr/bin/env python3
"""Construit un snapshot de revue sans modifier les données servies en production."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monitor import infer_engine, infer_vehicle_identity
from scan_deals import compute_trust_score, enrichment_for, legal_signal_for
from tools.validate_enrichments import validate, validate_legal_signals


def build_preview(
    snapshot: dict[str, Any],
    enrichments: dict[str, Any],
    legal_signals: dict[str, Any],
    criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = validate(snapshot, enrichments)
    if not report["valid"]:
        raise ValueError(f"table d'enrichissement invalide: {report['errors']}")
    legal_report = validate_legal_signals(snapshot, legal_signals)
    if not legal_report["valid"]:
        raise ValueError(f"table de risques invalide: {legal_report['errors']}")

    enrichment_by_url = {item["url"]: item for item in enrichments["listings"]}
    deals = []
    for original in snapshot["deals"]:
        deal = dict(original)
        entry = enrichment_by_url[deal["url"]]
        deal["engine"] = deal.get("engine") or infer_engine(
            " ".join(str(deal.get(field) or "") for field in ("title", "description", "url"))
        )
        identity = infer_vehicle_identity(" ".join(str(deal.get(field) or "") for field in ("title", "description", "url")))
        for field in ("make", "model", "cab", "cab_class"):
            deal[field] = deal.get(field) or identity[field]
        fuel = entry.get("fuel_economy", {})
        if fuel.get("status") == "confirmed":
            # Ces deux valeurs proviennent de la table certifiée déjà validée;
            # elles ne sont utilisées que par cet artefact de prévisualisation.
            deal["transmission"] = fuel["match"]["transmission"]
            deal["drivetrain"] = fuel["match"]["drivetrain"]
        deal.update(enrichment_for(deal["url"], deal, enrichments))
        deal["seller_legal_signal"] = legal_signal_for(deal["url"], legal_signals)
        deal["trust_score"] = compute_trust_score(
            deal["seller_reputation"], deal["seller_legal_signal"], snapshot["last_checked_at"][:10]
        )
        deals.append(deal)

    return {
        **snapshot,
        "schema_version": 2,
        "preview": True,
        "criteria": criteria or snapshot.get("criteria", {}),
        "deals": deals,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=Path, default=Path("docs/data/deals.json"))
    parser.add_argument("--enrichments", type=Path, default=Path("data/enrichments.json"))
    parser.add_argument("--legal-signals", type=Path, default=Path("data/seller_legal_signals.json"))
    parser.add_argument("--sources", type=Path, default=Path("data/sources.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/data/deals.preview.json"))
    args = parser.parse_args()
    preview = build_preview(
        json.loads(args.deals.read_text(encoding="utf-8")),
        json.loads(args.enrichments.read_text(encoding="utf-8")),
        json.loads(args.legal_signals.read_text(encoding="utf-8")),
        json.loads(args.sources.read_text(encoding="utf-8"))["criteria"],
    )
    args.output.write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
