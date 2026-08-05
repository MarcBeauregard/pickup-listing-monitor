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
    "cab_class": "crew_cab",
    "make": "Ford",
    "model": "F-150",
    "transmission": "automatic",
    "drivetrain": "4WD",
}

ENRICHMENTS = {
    "schema_version": 1,
    "listings": [{
        "url": "https://www.autohebdo.net/annonces/ford-f-150-lariat-supercrew-2-7-ecoboost-test-123",
        "seller_reputation": {
            "status": "confirmed",
            "name": "Garage Test",
            "rating": 4.7,
            "review_count": 321,
            "source_url": "https://maps.google.com/?cid=123",
            "verified_at": "2026-08-05",
        },
        "fuel_economy": {
            "status": "confirmed",
            "city_l_per_100km": 12.8,
            "highway_l_per_100km": 10.0,
            "source_url": "https://fcr-ccc.nrcan-rncan.gc.ca/",
            "verified_at": "2026-08-05",
            "match": {"year": 2022, "engine": "2.7L EcoBoost", "transmission": "automatic (AS10, 10 vitesses)", "drivetrain": "4x4/4WD"},
        },
    }],
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

    def test_discovers_custom_relative_listing_paths(self):
        source = {
            "listing_domain": "dealer.test",
            "base_url": "https://dealer.test",
            "listing_path_pattern": r"/used/[^\"'<>\s]+",
            "max_listings": 10,
        }
        urls = scan_deals.discover_urls('<a href="/used/tacoma-123?campaign=x">Tacoma</a>', source)
        self.assertEqual(urls, ["https://dealer.test/used/tacoma-123"])

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

    def test_monthly_range_is_enforced_from_tax_inclusive_payment(self):
        criteria = {**CONFIG["criteria"], "max_price": 60000, "min_monthly": 500, "max_monthly": 700}
        high = scan_deals.evaluate({**DETAIL, "price": 43499}, criteria)
        low = scan_deals.evaluate({**DETAIL, "price": 25000}, criteria)
        self.assertFalse(high[0])
        self.assertIn("paiement estimé au-dessus de la fourchette", high[1])
        self.assertFalse(low[0])
        self.assertIn("paiement estimé sous la fourchette", low[1])

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

    def test_multiple_sources_deduplicate_the_same_listing(self):
        config = {**CONFIG, "sources": [CONFIG["sources"][0], {**CONFIG["sources"][0], "name": "fixture-2"}]}
        result = scan_deals.scan(
            config,
            previous=None,
            timeout=1,
            source_fetcher=lambda *_: SOURCE_HTML,
            listing_fetcher=lambda *_: DETAIL,
        )
        self.assertEqual(result["counts"]["discovered"], 1)

    def test_enrichment_requires_exact_mechanical_match(self):
        result = scan_deals.scan(
            CONFIG,
            previous=None,
            timeout=1,
            source_fetcher=lambda *_: SOURCE_HTML,
            listing_fetcher=lambda *_: DETAIL,
            enrichments=ENRICHMENTS,
        )
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["deals"][0]["seller_reputation"]["rating"], 4.7)
        self.assertEqual(result["deals"][0]["fuel_economy"]["city_l_per_100km"], 12.8)

        mismatch = scan_deals.enrichment_for(
            ENRICHMENTS["listings"][0]["url"],
            {**DETAIL, "drivetrain": "2WD"},
            ENRICHMENTS,
        )
        self.assertEqual(mismatch["fuel_economy"], {"status": "unconfirmed", "reason": "configuration mécanique non concordante"})

        unsafe = scan_deals.enrichment_for(
            ENRICHMENTS["listings"][0]["url"],
            DETAIL,
            {"listings": [{
                **ENRICHMENTS["listings"][0],
                "seller_reputation": {**ENRICHMENTS["listings"][0]["seller_reputation"], "source_url": "javascript:alert(1)"},
            }]},
        )
        self.assertEqual(unsafe["seller_reputation"], {"status": "unconfirmed", "name": "Garage Test"})

    def test_unconfirmed_seller_keeps_identity_and_reason_without_rating(self):
        value = scan_deals.enrichment_for(
            ENRICHMENTS["listings"][0]["url"],
            DETAIL,
            {"listings": [{
                "url": ENRICHMENTS["listings"][0]["url"],
                "seller_reputation": {
                    "status": "unconfirmed",
                    "name": "Commerce homonyme",
                    "reason": "adresse Google ambiguë",
                    "rating": 4.9,
                },
            }]},
        )["seller_reputation"]
        self.assertEqual(value, {"status": "unconfirmed", "name": "Commerce homonyme", "reason": "adresse Google ambiguë"})

    def test_old_listing_without_enrichment_stays_readable(self):
        result = scan_deals.scan(
            CONFIG,
            previous=None,
            timeout=1,
            source_fetcher=lambda *_: SOURCE_HTML,
            listing_fetcher=lambda *_: DETAIL,
        )
        deal = result["deals"][0]
        self.assertEqual(deal["seller_reputation"], {"status": "unconfirmed"})
        self.assertEqual(deal["fuel_economy"], {"status": "unconfirmed"})

    def test_tacoma_profile_accepts_double_cab_and_rejects_access_cab(self):
        criteria = {
            "min_year": 2020,
            "max_price": 40000,
            "max_mileage": 120000,
            "profiles": [{"model": "Tacoma", "cab_classes": ["double_cab"], "cab_reason": "Tacoma Double Cab non confirmé"}],
        }
        base = {"status": "active", "price": 36000, "year": 2022, "mileage": 80000, "model": "Tacoma", "title": "Toyota Tacoma SR5 V6", "cab": "Double Cab", "cab_class": "double_cab"}
        self.assertTrue(scan_deals.evaluate(base, criteria)[0])
        rejected = scan_deals.evaluate({**base, "cab": "Access Cab", "cab_class": "access_cab"}, criteria)
        self.assertFalse(rejected[0])
        self.assertIn("Tacoma Double Cab non confirmé", rejected[1])


if __name__ == "__main__":
    unittest.main()
