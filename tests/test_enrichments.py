import json
import unittest
from pathlib import Path

from tools.build_enriched_preview import build_preview
from tools.validate_enrichments import validate


ROOT = Path(__file__).resolve().parents[1]


class EnrichmentContractTests(unittest.TestCase):
    def test_certified_table_matches_the_twenty_existing_listings(self):
        snapshot = json.loads((ROOT / "docs/data/deals.json").read_text(encoding="utf-8"))
        enrichments = json.loads((ROOT / "data/enrichments.json").read_text(encoding="utf-8"))
        report = validate(snapshot, enrichments)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["snapshot_urls"], 20)
        self.assertEqual(report["unique_enrichment_urls"], 20)
        self.assertEqual(report["duplicate_snapshot_urls"], [])
        self.assertEqual(report["duplicate_urls"], [])
        self.assertEqual(report["orphan_urls"], [])
        self.assertEqual(report["missing_urls"], [])
        self.assertEqual(report["seller_confirmed"], 13)
        self.assertEqual(report["fuel_confirmed"], 6)
        self.assertEqual(report["mechanical_year_engine_matches"], 6)

    def test_preview_contains_confirmed_and_unconfirmed_examples(self):
        snapshot = json.loads((ROOT / "docs/data/deals.json").read_text(encoding="utf-8"))
        enrichments = json.loads((ROOT / "data/enrichments.json").read_text(encoding="utf-8"))
        preview = build_preview(snapshot, enrichments)
        self.assertEqual(len(preview["deals"]), 20)
        self.assertEqual(
            sum(deal["seller_reputation"]["status"] == "confirmed" for deal in preview["deals"]),
            13,
        )
        self.assertEqual(
            sum(deal["fuel_economy"]["status"] == "confirmed" for deal in preview["deals"]),
            6,
        )
        self.assertTrue(any(deal["seller_reputation"]["status"] == "unconfirmed" for deal in preview["deals"]))
        self.assertTrue(any(deal["fuel_economy"]["status"] == "unconfirmed" for deal in preview["deals"]))


if __name__ == "__main__":
    unittest.main()
