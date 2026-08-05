import unittest

import scan_deals


SOURCE_HTML = """
<a href="https://www.autohebdo.net/annonces/ford-f-150-lariat-supercrew-2-7-ecoboost-test-123">Voir</a>
"""

DETAIL = {
    "status": "active",
    "price": 37887,
    "title": "2022 Ford F-150 Lariat SuperCrew 2.7L EcoBoost",
    "description": "Cuir, écran 12 pouces, cabine SuperCrew",
    "image": "https://images.test/f150.webp",
    "mileage": 98500,
    "year": 2022,
    "location": "Saint-Hyacinthe, Quebec",
    "engine": "2.7L EcoBoost",
    "trim": "Lariat",
    "cab": "SuperCrew",
}

CONFIG = {
    "criteria": {
        "min_year": 2020,
        "max_price": 40000,
        "max_mileage": 120000,
        "engine_terms": ["2.7", "3.5", "ecoboost"],
        "trims": ["Lariat", "XLT"],
        "require_supercrew": True,
    },
    "sources": [{
        "name": "fixture",
        "url": "https://search.test",
        "listing_domain": "www.autohebdo.net",
        "max_listings": 10,
    }],
}


class ScanDealsTests(unittest.TestCase):
    def test_discovers_unique_listing_urls(self):
        urls = scan_deals.discover_urls(SOURCE_HTML + SOURCE_HTML, CONFIG["sources"][0])
        self.assertEqual(len(urls), 1)

    def test_new_deal_appears_then_is_not_new_on_next_run(self):
        first = scan_deals.scan(
            CONFIG,
            previous=None,
            timeout=1,
            source_fetcher=lambda *_: SOURCE_HTML,
            listing_fetcher=lambda *_: DETAIL,
        )
        self.assertEqual(first["counts"], {"discovered": 1, "eligible": 1, "new": 1, "new_eligible": 1, "new_in_run": 1})
        self.assertTrue(first["deals"][0]["is_new"])

        second = scan_deals.scan(
            CONFIG,
            previous=first,
            timeout=1,
            source_fetcher=lambda *_: SOURCE_HTML,
            listing_fetcher=lambda *_: DETAIL,
        )
        self.assertEqual(second["counts"]["new_in_run"], 0)
        self.assertTrue(second["deals"][0]["is_new"])
        self.assertEqual(second["deals"][0]["first_seen_at"], first["deals"][0]["first_seen_at"])

    def test_monthly_payment_includes_quebec_taxes(self):
        self.assertEqual(scan_deals.monthly_payment(37887), 657)

    def test_rejects_high_mileage(self):
        current = {**DETAIL, "mileage": 137582}
        eligible, reasons, _score = scan_deals.evaluate(current, CONFIG["criteria"])
        self.assertFalse(eligible)
        self.assertIn("kilométrage au-dessus de la cible", reasons)

    def test_empty_source_is_reported_as_partial(self):
        result = scan_deals.scan(
            CONFIG,
            previous=None,
            timeout=1,
            source_fetcher=lambda *_: "<html>aucune fiche reconnue</html>",
            listing_fetcher=lambda *_: DETAIL,
        )
        self.assertEqual(result["scan_status"], "partial")
        self.assertEqual(result["counts"]["discovered"], 0)
        self.assertIn("structure possiblement changée", result["source_errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
