import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutomationContractTests(unittest.TestCase):
    def test_client_contains_no_repository_secret(self):
        client = "\n".join(
            (ROOT / "docs" / name).read_text(encoding="utf-8")
            for name in ("index.html", "app.js", "config.js")
        ).lower()
        for forbidden in ("github_token", "authorization: bearer", "ghp_", "github_pat_"):
            self.assertNotIn(forbidden, client)

    def test_scheduled_workflow_runs_scanner_without_llm(self):
        workflow = (ROOT / ".github" / "workflows" / "pickup-watch.yml").read_text(encoding="utf-8").lower()
        self.assertIn("schedule:", workflow)
        self.assertIn("python3 scan_deals.py", workflow)
        self.assertNotIn("openai", workflow)
        self.assertNotIn("anthropic", workflow)

    def test_real_snapshot_has_expected_dashboard_shape(self):
        snapshot = json.loads((ROOT / "docs" / "data" / "deals.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["scan_status"], "ok")
        self.assertGreaterEqual(snapshot["counts"]["discovered"], 1)
        self.assertTrue(all("image" in deal and "checked_at" in deal for deal in snapshot["deals"]))


if __name__ == "__main__":
    unittest.main()

