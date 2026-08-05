import json
import unittest
from pathlib import Path

from tools.build_enriched_preview import build_preview
from tools.validate_enrichments import validate, validate_legal_signals


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
        legal_signals = json.loads((ROOT / "data/seller_legal_signals.json").read_text(encoding="utf-8"))
        preview = build_preview(snapshot, enrichments, legal_signals)
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

    def test_legal_table_reproduces_five_audited_cases(self):
        snapshot = json.loads((ROOT / "docs/data/deals.json").read_text(encoding="utf-8"))
        signals = json.loads((ROOT / "data/seller_legal_signals.json").read_text(encoding="utf-8"))
        report = validate_legal_signals(snapshot, signals)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["entries"], 7)
        self.assertEqual(report["unique_cases"], 5)
        self.assertEqual((report["red"], report["yellow"], report["unattributed"]), (5, 1, 1))
        by_case = {}
        for item in signals["listings"]:
            by_case.setdefault(item["case_id"], item)
        self.assertEqual(
            {case_id: item["status"] for case_id, item in by_case.items()},
            {
                "hgregoire-carignan": "red",
                "automobile-en-direct-laval": "red",
                "centre-liquidation-bd": "red",
                "st-basile-honda": "yellow",
                "auto-durocher-mirabel": "unattributed",
            },
        )
        durocher = by_case["auto-durocher-mirabel"]
        self.assertEqual(durocher["match_status"], "different_entity")
        self.assertFalse(durocher["branch_matched"])
        self.assertIn("signal non attribué", durocher["nature"])


if __name__ == "__main__":
    unittest.main()
