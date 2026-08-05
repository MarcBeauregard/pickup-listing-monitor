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
        "min_year": 2017,
        "max_price": 40000,
        "min_monthly": 500,
        "max_monthly": 700,
        "max_mileage": 120000,
        "priority": {"make": "Toyota", "model": "Tacoma", "cab_class": "double_cab", "score_bonus": 15},
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
        self.assertEqual(first["counts"], {"discovered": 1, "eligible": 1, "high_mileage": 0, "new": 1, "new_eligible": 1, "new_in_run": 1})
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
        self.assertTrue(scan_deals.is_high_mileage_only(current, CONFIG["criteria"]))

    def test_120000_is_eligible_and_120001_is_high_mileage_never_alertable(self):
        candidates = {"admissibles": [
            {"url": "https://www.autohebdo.net/annonces/honda-ridgeline-120000", "marque": "Honda", "modele": "Ridgeline", "cabine": "Crew Cab", "annee": 2020, "km": 120000, "prix": 32000, "mensualite_calculee": 555.0, "vendeur": "Garage A", "ville": "Granby", "distance_estimee_km": 30, "statut": "admissible"},
            {"url": "https://www.autohebdo.net/annonces/honda-ridgeline-120001", "marque": "Honda", "modele": "Ridgeline", "cabine": "Crew Cab", "annee": 2020, "km": 120001, "prix": 32000, "mensualite_calculee": 555.0, "vendeur": "Garage B", "ville": "Granby", "distance_estimee_km": 30, "statut": "admissible"},
        ]}
        by_url = {
            row["url"]: {**DETAIL, "title": "Honda Ridgeline Crew Cab", "price": row["prix"], "year": row["annee"], "mileage": row["km"], "make": "Honda", "model": "Ridgeline"}
            for row in candidates["admissibles"]
        }
        result = scan_deals.scan(
            {**CONFIG, "sources": []}, previous=None, timeout=1,
            listing_fetcher=lambda url, _timeout: by_url[url], candidates=candidates,
        )
        eligible = next(item for item in result["deals"] if item["mileage"] == 120000)
        high = next(item for item in result["deals"] if item["mileage"] == 120001)
        self.assertTrue(eligible["eligible"])
        self.assertFalse(high["eligible"])
        self.assertTrue(high["high_mileage"])
        self.assertFalse(high["alert_eligible"])
        self.assertEqual(high["candidate_status"], "high_mileage")

    def test_accepts_2017_and_rejects_2016_for_any_model(self):
        generic = {**DETAIL, "make": "Honda", "model": "Ridgeline", "cab_class": "crew_cab", "price": 32000}
        self.assertTrue(scan_deals.evaluate({**generic, "year": 2017}, CONFIG["criteria"])[0])
        rejected = scan_deals.evaluate({**generic, "year": 2016}, CONFIG["criteria"])
        self.assertFalse(rejected[0])
        self.assertIn("année hors cible ou inconnue", rejected[1])

    def test_unknown_make_and_model_are_not_silently_excluded(self):
        future_source = {**DETAIL, "make": None, "model": None, "cab_class": "unknown", "price": 32000, "year": 2019}
        self.assertTrue(scan_deals.evaluate(future_source, CONFIG["criteria"])[0])

    def test_tacoma_double_cab_is_priority_not_an_exclusion(self):
        base = {**DETAIL, "make": "Toyota", "model": "Tacoma", "price": 32000}
        double_cab = scan_deals.evaluate({**base, "cab_class": "double_cab"}, CONFIG["criteria"])
        access_cab = scan_deals.evaluate({**base, "cab_class": "access_cab"}, CONFIG["criteria"])
        self.assertTrue(double_cab[0])
        self.assertTrue(access_cab[0])
        self.assertEqual(double_cab[2] - access_cab[2], 15)

    def test_tacoma_priority_requires_explicit_double_cab_proof(self):
        explicit = {"marque": "Toyota", "modele": "Tacoma", "cabine": "Double Cab", "preuve_cabine": 'Titre "Double Cab"'}
        indirect = {"marque": "Toyota", "modele": "Tacoma", "cabine": "Double Cab", "preuve_cabine": "Portes : 4"}
        self.assertEqual(scan_deals.candidate_cab(explicit), ("Double Cab", "double_cab"))
        self.assertEqual(scan_deals.candidate_cab(indirect), (None, "unknown"))

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

    def test_legal_signal_never_inherits_by_similar_seller_name(self):
        url = ENRICHMENTS["listings"][0]["url"]
        signal = {
            "case_id": "durocher-laval",
            "url": url,
            "status": "unattributed",
            "nature": "Homonymie / entité différente — signal non attribué",
            "event_type": "condamnation non attribuée",
            "event_date": "2021-10-17",
            "legal_entity": "Entité Mirabel; autre entité Laval",
            "permit_or_neq": "permis distinct",
            "branch": "Auto Durocher Mirabel",
            "source_url": "https://example.test/source",
            "source_checked_at": "2026-08-05",
            "match_status": "different_entity",
            "match_basis": "raisons sociales différentes",
            "branch_matched": False,
        }
        signals = {"checked_at": "2026-08-05", "listings": [signal]}
        self.assertEqual(scan_deals.legal_signal_for(url, signals)["status"], "unattributed")
        self.assertEqual(
            scan_deals.legal_signal_for("https://example.test/autre-succursale", signals),
            {"status": "not_audited", "source_checked_at": "2026-08-05"},
        )

    def test_attributed_alert_requires_exact_branch_match(self):
        url = ENRICHMENTS["listings"][0]["url"]
        invalid = {
            "url": url,
            "status": "red",
            "nature": "Condamnation",
            "event_type": "jugement",
            "event_date": "2026-01-17",
            "legal_entity": "Entité test",
            "permit_or_neq": "permis test",
            "branch": "Autre succursale",
            "source_url": "https://example.test/source",
            "source_checked_at": "2026-08-05",
            "match_status": "different_entity",
            "match_basis": "nom seulement",
            "branch_matched": False,
        }
        self.assertEqual(
            scan_deals.legal_signal_for(url, {"checked_at": "2026-08-05", "listings": [invalid]}),
            {"status": "not_audited", "source_checked_at": "2026-08-05"},
        )

    def test_multibrand_legal_mapping_preserves_entity_only_branch_scope(self):
        url = "https://www.autohebdo.net/annonces/ram-1500-test"
        mapping = {
            "generated_at": "2026-08-05",
            "sources": {"automobile_en_direct_conviction": "https://www.opc.gouv.qc.ca/source"},
            "entries": [{
                "url": url, "seller": "Automobile en direct - Québec", "branch": "Québec",
                "legal_entity": "AUTOMOBILE EN DIRECT.COM INC.", "permit": "2110323-1",
                "entity_match": "exact", "branch_match": "entity_only_branch_not_named_in_event",
                "applicable": True, "severity": "red", "event_type": "guilty_plea",
                "event_date": "2025-03-27",
                "display_note": "Même entité; la succursale de Québec n’est pas nommée comme lieu des infractions.",
            }],
        }
        signal = scan_deals.mapped_legal_signal_for(url, mapping)
        self.assertEqual(signal["status"], "red")
        self.assertFalse(signal["branch_matched"])
        self.assertEqual(signal["branch_scope"], "entity_only_branch_not_named_in_event")
        self.assertIn("n’est pas nommée", signal["nature"])

    def test_trust_score_legal_bands_and_missing_data_floors(self):
        reputation = {
            "status": "confirmed", "rating": 4.1, "review_count": 1311,
            "source_url": "https://maps.example/seller", "verified_at": "2026-08-05",
        }
        red = scan_deals.compute_trust_score(reputation, {"status": "red", "nature": "Entente", "source_url": "https://law.example/red"}, "2026-08-05")
        yellow = scan_deals.compute_trust_score({**reputation, "rating": 4.5, "review_count": 2326}, {"status": "yellow"}, "2026-08-05")
        missing_red = scan_deals.compute_trust_score({"status": "unconfirmed"}, {"status": "red"}, "2026-08-05")
        homonymy = scan_deals.compute_trust_score({"status": "unconfirmed"}, {"status": "unattributed"}, "2026-08-05")
        self.assertEqual(red["score"], 17.48)
        self.assertLessEqual(red["score"], 20)
        self.assertEqual(yellow["score"], 47.97)
        self.assertLessEqual(yellow["score"], 50)
        self.assertEqual(missing_red["score"], 0)
        self.assertEqual(homonymy["score"], 51)

    def test_non_audited_score_caps_at_80_and_missing_stays_null(self):
        perfect = scan_deals.compute_trust_score(
            {"status": "confirmed", "rating": 5.0, "review_count": 23, "source_url": "https://maps.example/seller", "verified_at": "2026-08-05"},
            {"status": "not_audited"},
            "2026-08-05",
        )
        missing = scan_deals.compute_trust_score({"status": "unconfirmed"}, {"status": "not_audited"}, "2026-08-05")
        self.assertEqual(perfect["components"]["volume_points"], 9.2)
        self.assertEqual(perfect["score"], 80)
        self.assertIsNone(missing["score"])

    def test_trust_freshness_thresholds_are_monotonic(self):
        expected_freshness = {
            "2026-08-05": 1.0,
            "2026-07-06": 1.0,
            "2026-05-07": 0.95,
            "2026-02-05": 0.90,
            "2025-08-05": 0.80,
        }
        scores = []
        for verified_at, expected in expected_freshness.items():
            result = scan_deals.compute_trust_score(
                {"status": "confirmed", "rating": 4.0, "review_count": 100, "verified_at": verified_at},
                {"status": "red"},
                "2026-08-05",
            )
            self.assertEqual(result["components"]["freshness_multiplier"], expected)
            self.assertLessEqual(result["score"], 20)
            scores.append(result["score"])
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_trust_freshness_exact_90_day_boundary(self):
        before = scan_deals.compute_trust_score(
            {"status": "confirmed", "rating": 4.0, "review_count": 100, "verified_at": "2026-05-08"},
            {"status": "yellow"},
            "2026-08-05",
        )
        exact = scan_deals.compute_trust_score(
            {"status": "confirmed", "rating": 4.0, "review_count": 100, "verified_at": "2026-05-07"},
            {"status": "yellow"},
            "2026-08-05",
        )
        self.assertEqual(before["components"]["freshness_multiplier"], 1.0)
        self.assertEqual(exact["components"]["freshness_multiplier"], 0.95)
        self.assertLessEqual(exact["score"], 50)

    def test_invalid_missing_and_future_dates_apply_the_worst_freshness(self):
        base = {"status": "confirmed", "rating": 5.0, "review_count": 1000}
        for verified_at in (None, "not-a-date", "2026-08-06"):
            seller = {**base}
            if verified_at is not None:
                seller["verified_at"] = verified_at
            result = scan_deals.compute_trust_score(seller, {"status": "not_audited"}, "2026-08-05")
            self.assertEqual(result["score"], 50.0)
            self.assertEqual(result["components"]["freshness_multiplier"], 0.5)
            self.assertTrue(result["components"]["date_invalid_or_missing"])
            self.assertTrue(any("fraîcheur minimale" in reason for reason in result["reasons"]))

    def test_better_google_rating_never_escapes_legal_cap(self):
        for status, cap in (("red", 20), ("yellow", 50), ("unattributed", 70), ("not_audited", 80)):
            lower = scan_deals.compute_trust_score(
                {"status": "confirmed", "rating": 2.0, "review_count": 50, "verified_at": "2026-08-05"},
                {"status": status},
                "2026-08-05",
            )
            higher = scan_deals.compute_trust_score(
                {"status": "confirmed", "rating": 5.0, "review_count": 5000, "verified_at": "2026-08-05"},
                {"status": status},
                "2026-08-05",
            )
            self.assertLessEqual(lower["score"], higher["score"])
            self.assertLessEqual(higher["score"], cap)

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

    def test_tacoma_access_cab_remains_eligible_under_generic_scope(self):
        criteria = {
            "min_year": 2017,
            "max_price": 40000,
            "min_monthly": 500,
            "max_monthly": 700,
            "max_mileage": 120000,
            "priority": {"make": "Toyota", "model": "Tacoma", "cab_class": "double_cab", "score_bonus": 15},
        }
        base = {"status": "active", "price": 36000, "year": 2022, "mileage": 80000, "make": "Toyota", "model": "Tacoma", "title": "Toyota Tacoma SR5 V6", "cab": "Double Cab", "cab_class": "double_cab"}
        self.assertTrue(scan_deals.evaluate(base, criteria)[0])
        access = scan_deals.evaluate({**base, "cab": "Access Cab", "cab_class": "access_cab"}, criteria)
        self.assertTrue(access[0])


if __name__ == "__main__":
    unittest.main()
