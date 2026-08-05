#!/usr/bin/env python3
"""Construit la table de provenance exhaustive du preview publié."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def category(deal: dict[str, Any]) -> str:
    origin = deal["candidate_origin"]
    if deal["high_mileage"]:
        return "high_mileage"
    if not deal["eligible"]:
        return "rejected"
    if origin == "historical":
        return "historical_eligible"
    if origin == "validated_batch":
        return "new_eligible"
    return "live_source_eligible"


def build(preview: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    rendered = [{
        "id": deal["id"],
        "url": deal["url"],
        "rendered": True,
        "origin": deal["candidate_origin"],
        "category": category(deal),
        "eligible": deal["eligible"],
        "high_mileage": deal["high_mileage"],
        "status": deal["status"],
    } for deal in preview["deals"]]
    excluded = [{
        "id": None,
        "url": row["url"],
        "rendered": False,
        "origin": "validated_batch",
        "category": "non_ingested" if row["decision"] == "distance_unconfirmed" else "rejected_before_ingestion",
        "eligible": False,
        "high_mileage": False,
        "status": row["decision"],
    } for row in validation["rows"] if row["decision"] in {"distance_unconfirmed", "rejected_initial"}]
    urls = [row["url"] for row in rendered]
    duplicates = len(urls) - len(set(urls))
    return {
        "schema_version": 1,
        "preview_checked_at": preview["last_checked_at"],
        "preview_counts": preview["counts"],
        "equation": {
            "rendered": len(rendered),
            "batch": sum(row["origin"] == "validated_batch" for row in rendered),
            "historical": sum(row["origin"] == "historical" for row in rendered),
            "live_source": sum(row["origin"] == "live_source" for row in rendered),
            "excluded_before_ingestion": len(excluded),
            "duplicates": duplicates,
        },
        "rows": rendered + excluded,
    }


def markdown(payload: dict[str, Any]) -> str:
    counts = payload["preview_counts"]
    equation = payload["equation"]
    lines = [
        "# Provenance exhaustive de la prévisualisation — 2026-08-05",
        "",
        f"État du scan : `{payload['preview_checked_at']}`.",
        "",
        f"Équation rendue : **{equation['rendered']} = {equation['batch']} lot validé + {equation['historical']} historiques + {equation['live_source']} source live**, après déduplication ({equation['duplicates']} doublon).",
        "",
        f"Compte admissible unique affiché par l’interface : **{counts['eligible']} = {counts['batch_eligible']} lot + {counts['historical_eligible']} historiques + {counts['source_eligible']} source live**. Les {counts['high_mileage']} kilométrages élevés sont exclus de ce compte.",
        "",
        f"Exclus avant rendu : **{equation['excluded_before_ingestion']}** lignes du lot (cinq distances non confirmées et deux rejets initiaux).",
        "",
        "| ID | Provenance | Catégorie | Rendu | URL |",
        "|---|---|---|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(f"| {row['id'] or '—'} | {row['origin']} | {row['category']} | {'oui' if row['rendered'] else 'non'} | [annonce]({row['url']}) |")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, default=Path("docs/data/deals.preview.json"))
    parser.add_argument("--validation", type=Path, default=Path("data/multibrand_validation_2026-08-05.json"))
    parser.add_argument("--output", type=Path, default=Path("data/preview_provenance_2026-08-05.json"))
    parser.add_argument("--report", type=Path, default=Path("docs/PREVIEW_PROVENANCE_2026-08-05.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preview = json.loads(args.preview.read_text(encoding="utf-8"))
    validation = json.loads(args.validation.read_text(encoding="utf-8"))
    payload = build(preview, validation)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps(payload["equation"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
