import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

import validate_multibrand_candidates as validator


ROOT = Path(__file__).resolve().parents[1]


class MultibrandContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidates = json.loads((ROOT / "data" / "multibrand_candidates_2026-08-05.json").read_text(encoding="utf-8"))
        cls.validation = json.loads((ROOT / "data" / "multibrand_validation_2026-08-05.json").read_text(encoding="utf-8"))
        cls.mapping_path = ROOT / "data" / "multibrand_legal_mapping_2026-08-05.json"
        cls.mapping = json.loads(cls.mapping_path.read_text(encoding="utf-8"))

    def test_source_has_exact_99_unique_rows_and_original_counts(self):
        rows = validator.flatten(self.candidates)
        self.assertEqual({key: len(self.candidates[key]) for key in validator.GROUPS}, {"admissibles": 92, "non_confirmes": 5, "rejetes": 2})
        self.assertEqual(len(rows), 99)
        self.assertEqual(len({row["url"] for _group, row in rows}), 99)

    def test_validation_reproduces_final_decisions(self):
        self.assertEqual(
            self.validation["decision_counts"],
            {"eligible": 64, "high_mileage": 27, "rejected_inactive": 1, "distance_unconfirmed": 5, "rejected_initial": 2},
        )
        self.assertFalse(any(row["duplicate_with_existing"] or row["duplicate_in_batch"] for row in self.validation["rows"]))
        self.assertTrue(all(row.get("validated", {}).get("monthly", 500) >= 500 for row in self.validation["rows"] if row["decision"] in {"eligible", "high_mileage"}))
        self.assertTrue(all(row.get("validated", {}).get("monthly", 700) <= 700 for row in self.validation["rows"] if row["decision"] in {"eligible", "high_mileage"}))

    def test_only_three_tacomas_have_explicit_double_cab_proof(self):
        tacomas = [row for row in self.candidates["admissibles"] if row["marque"] == "Toyota" and row["modele"] == "Tacoma"]
        explicit = [row for row in tacomas if validator.explicit_tacoma_double_cab(row)]
        self.assertEqual(len(explicit), 3)
        indirect = next(row for row in tacomas if row["annee"] == 2023)
        self.assertFalse(validator.explicit_tacoma_double_cab(indirect))

    def test_legal_mapping_hash_urls_and_severities_are_exact(self):
        digest = hashlib.sha256(self.mapping_path.read_bytes()).hexdigest()
        self.assertEqual(digest, "ed28e24e26a629d7fb9e2dd163f765a41a5b22d7f87e578c908beb9ea4bc4205")
        entries = self.mapping["entries"]
        marked = {row["url"] for row in self.candidates["admissibles"] if row.get("risque_vendeur_connu")}
        self.assertEqual(len(entries), 15)
        self.assertEqual({entry["url"] for entry in entries}, marked)
        self.assertEqual(Counter(entry["severity"] for entry in entries), Counter({"red": 14, "yellow": 1}))
        self.assertTrue(all(entry["entity_match"] == "exact" and entry["applicable"] is True for entry in entries))
        self.assertTrue(all(entry["branch_match"] in {"exact_event_branch", "exact_trade_name_and_city", "entity_only_branch_not_named_in_event", "entity_head_office_not_named_in_event"} for entry in entries))

    def test_preview_excludes_high_mileage_from_alerts_and_keeps_indirect_tacoma_unknown(self):
        preview = json.loads((ROOT / "docs" / "data" / "deals.preview.json").read_text(encoding="utf-8"))
        self.assertEqual(preview["counts"]["batch_discovered"], 92)
        self.assertEqual(preview["counts"]["batch_eligible"], 64)
        self.assertEqual(preview["counts"]["batch_high_mileage"], 27)
        self.assertEqual(preview["counts"]["historical_discovered"], 20)
        self.assertEqual(preview["counts"]["eligible"], preview["counts"]["batch_eligible"] + preview["counts"]["historical_eligible"] + preview["counts"]["source_eligible"])
        self.assertEqual(preview["counts"]["discovered"], preview["counts"]["batch_discovered"] + preview["counts"]["historical_discovered"] + preview["counts"]["source_discovered"])
        self.assertFalse(any(row["high_mileage"] and row["alert_eligible"] for row in preview["deals"]))
        tacoma_2023 = next(row for row in preview["deals"] if row.get("make") == "Toyota" and row.get("model") == "Tacoma" and row.get("year") == 2023)
        self.assertEqual(tacoma_2023["cab_class"], "unknown")
        self.assertFalse(tacoma_2023["eligible"])

    def test_preview_provenance_reconciles_batch_historical_and_live_source(self):
        preview = json.loads((ROOT / "docs" / "data" / "deals.preview.json").read_text(encoding="utf-8"))
        provenance = json.loads((ROOT / "data" / "preview_provenance_2026-08-05.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["equation"], {
            "rendered": 127, "batch": 92, "historical": 20, "live_source": 15,
            "excluded_before_ingestion": 7, "duplicates": 0,
        })
        rendered = [row for row in provenance["rows"] if row["rendered"]]
        self.assertEqual(len(rendered), preview["counts"]["discovered"])
        self.assertEqual({row["url"] for row in rendered}, {row["url"] for row in preview["deals"]})
        self.assertEqual(preview["counts"]["eligible"], 81)
        self.assertEqual(preview["counts"]["eligible"], preview["counts"]["batch_eligible"] + preview["counts"]["historical_eligible"] + preview["counts"]["source_eligible"])


if __name__ == "__main__":
    unittest.main()
