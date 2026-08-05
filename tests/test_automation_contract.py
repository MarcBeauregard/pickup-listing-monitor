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
        self.assertIn("deploy_validated_snapshot:", workflow)
        self.assertIn("inputs.deploy_validated_snapshot != true", workflow)
        self.assertNotIn("openai", workflow)
        self.assertNotIn("anthropic", workflow)

    def test_validated_production_snapshot_has_reconciled_counts(self):
        snapshot = json.loads((ROOT / "docs" / "data" / "deals.json").read_text(encoding="utf-8"))
        counts = snapshot["counts"]
        self.assertEqual(counts["discovered"], 127)
        self.assertEqual(counts["eligible"], 81)
        self.assertEqual(counts["high_mileage"], 36)
        self.assertEqual(
            counts["discovered"],
            counts["batch_discovered"]
            + counts["historical_discovered"]
            + counts["source_discovered"],
        )

    def test_real_snapshot_has_expected_dashboard_shape(self):
        snapshot = json.loads((ROOT / "docs" / "data" / "deals.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["scan_status"], "ok")
        self.assertGreaterEqual(snapshot["counts"]["discovered"], 1)
        self.assertTrue(all("image" in deal and "checked_at" in deal for deal in snapshot["deals"]))

    def test_client_supports_legacy_snapshots_with_unconfirmed_enrichment(self):
        client = (ROOT / "docs" / "app.js").read_text(encoding="utf-8")
        self.assertIn('seller_reputation: { status: "unconfirmed" }', client)
        self.assertIn('fuel_economy: { status: "unconfirmed" }', client)
        self.assertIn('id="cab-filter"', (ROOT / "docs" / "index.html").read_text(encoding="utf-8"))

    def test_mobile_states_have_explicit_css_variants(self):
        styles = (ROOT / "docs" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('.empty-state[hidden]', styles)
        self.assertIn('.deal-card[data-eligible="true"] .match-badge', styles)

    def test_trust_control_uses_native_keyboard_accessible_disclosure(self):
        client = (ROOT / "docs" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "docs" / "styles.css").read_text(encoding="utf-8")
        render_trust = client[client.index("function renderTrust"):client.index("function setControlState")]
        self.assertIn('document.createElement("details")', render_trust)
        self.assertIn('document.createElement("summary")', render_trust)
        self.assertIn('summary.setAttribute("aria-label", `Confiance vendeur', render_trust)
        self.assertNotIn('summary.addEventListener("click"', render_trust)
        self.assertIn('trust.level !== "vigilance_homonymie"', render_trust)
        self.assertIn('trust.level === "rouge" ? "red"', render_trust)
        self.assertNotIn("Math.log", render_trust)
        self.assertNotIn("review_count +", render_trust)
        self.assertIn("Math.round(trust.score * 10) / 10", render_trust)
        self.assertIn('["Score exact", scoreVisible ?', render_trust)
        self.assertNotIn('["Score exact", trust.score == null', render_trust)
        self.assertIn("L’état compact arrondit à une décimale", render_trust)
        self.assertIn(".trust summary:focus-visible", styles)
        self.assertRegex(styles, r"\.trust summary \{[^}]*min-height:\s*44px")
        self.assertIn(".trust--red summary", styles)

    def test_listing_relevance_and_seller_trust_have_distinct_labels(self):
        client = (ROOT / "docs" / "app.js").read_text(encoding="utf-8")
        self.assertIn('`Pertinence ${deal.score}`', client)
        self.assertIn('`Confiance vendeur · ${scoreText}', client)
        self.assertNotIn('`Score ${deal.score}`', client)

    def test_filters_cover_multibrand_2017_and_cabins(self):
        page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        for selector in ("make-filter", "model-filter", "year-filter", "cab-filter"):
            self.assertIn(f'id="{selector}"', page)
        self.assertIn('<option value="2017">2017+</option>', page)
        self.assertIn('<option value="double_cab">Tacoma Double Cab</option>', page)
        self.assertIn('<option value="access_cab">Access Cab</option>', page)
        self.assertIn('id="include-high-mileage"', page)
        client = (ROOT / "docs" / "app.js").read_text(encoding="utf-8")
        self.assertIn("deal.high_mileage && !includeHighMileage", client)
        self.assertIn("Kilométrage élevé ·", client)
        self.assertIn('alert_eligible', (ROOT / "scan_deals.py").read_text(encoding="utf-8"))

    def test_entity_level_legal_risk_keeps_branch_nuance_visible(self):
        client = (ROOT / "docs" / "app.js").read_text(encoding="utf-8")
        self.assertIn("entity_only_branch_not_named_in_event", client)
        self.assertIn("entity_head_office_not_named_in_event", client)
        self.assertIn("cette succursale n’est pas nommée dans l’événement", client)


if __name__ == "__main__":
    unittest.main()
