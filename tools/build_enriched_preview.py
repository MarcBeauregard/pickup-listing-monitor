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

from monitor import infer_engine
from scan_deals import enrichment_for
from tools.validate_enrichments import validate


def build_preview(snapshot: dict[str, Any], enrichments: dict[str, Any]) -> dict[str, Any]:
    report = validate(snapshot, enrichments)
    if not report["valid"]:
        raise ValueError(f"table d'enrichissement invalide: {report['errors']}")

    enrichment_by_url = {item["url"]: item for item in enrichments["listings"]}
    deals = []
    for original in snapshot["deals"]:
        deal = dict(original)
        entry = enrichment_by_url[deal["url"]]
        deal["engine"] = deal.get("engine") or infer_engine(
            " ".join(str(deal.get(field) or "") for field in ("title", "description", "url"))
        )
        fuel = entry.get("fuel_economy", {})
        if fuel.get("status") == "confirmed":
            # Ces deux valeurs proviennent de la table certifiée déjà validée;
            # elles ne sont utilisées que par cet artefact de prévisualisation.
            deal["transmission"] = fuel["match"]["transmission"]
            deal["drivetrain"] = fuel["match"]["drivetrain"]
        deal.update(enrichment_for(deal["url"], deal, enrichments))
        deals.append(deal)

    return {**snapshot, "schema_version": 2, "preview": True, "deals": deals}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=Path, default=Path("docs/data/deals.json"))
    parser.add_argument("--enrichments", type=Path, default=Path("data/enrichments.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/data/deals.preview.json"))
    args = parser.parse_args()
    preview = build_preview(
        json.loads(args.deals.read_text(encoding="utf-8")),
        json.loads(args.enrichments.read_text(encoding="utf-8")),
    )
    args.output.write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
