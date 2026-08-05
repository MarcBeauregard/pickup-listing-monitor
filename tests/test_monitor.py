import io
import unittest
from urllib.error import HTTPError, URLError

import monitor


class FakeResponse:
    def __init__(self, body, status=200, url="https://example.test/listing"):
        self.body = body.encode("utf-8")
        self.status = status
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body

    def geturl(self):
        return self.url


class MonitorTests(unittest.TestCase):
    def test_extracts_price_from_json_ld_offer(self):
        page = '<script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer","price":"33555.00"}}</script>'
        self.assertEqual(monitor.extract_price(page), 33555)

    def test_extracts_price_from_meta(self):
        page = '<meta property="product:price:amount" content="31 998">'
        self.assertEqual(monitor.extract_price(page), 31998)

    def test_extracts_dashboard_metadata(self):
        page = """
        <meta property="og:title" content="2022 Ford F-150 LARIAT 502A Crew Cab 4x4 2.7T">
        <meta property="og:image" content="https://images.test/truck.webp">
        <meta name="description" content="F-150 Lariat SuperCrew 2,7 L EcoBoost cuir">
        <script>{"stmil":"97395","year":"2022","city":"ILE_PERROT","province":"Quebec"}</script>
        """
        result = monitor.extract_listing_metadata(page, "https://example.test/f150")
        self.assertEqual(result["year"], 2022)
        self.assertEqual(result["mileage"], 97395)
        self.assertEqual(result["trim"], "Lariat")
        self.assertEqual(result["cab"], "SuperCrew")
        self.assertEqual(result["engine"], "2.7L EcoBoost")
        self.assertEqual(result["location"], "Ile Perrot, Quebec")
        self.assertEqual(result["image"], "https://images.test/truck.webp")
        self.assertEqual(result["make"], "Ford")
        self.assertEqual(result["model"], "F-150")
        self.assertEqual(result["cab_class"], "crew_cab")
        self.assertEqual(result["drivetrain"], "4WD")

    def test_infers_ford_2_7t_as_ecoboost_without_description(self):
        self.assertEqual(
            monitor.infer_engine("2021 Ford F-150 XLT Crew Cab 4x4 2.7T"),
            "2.7L EcoBoost",
        )

    def test_tacoma_double_cab_is_distinct_from_access_cab(self):
        double_cab = monitor.extract_listing_metadata(
            '<h1>2022 Toyota Tacoma SR5 Double Cab 4x4 V6 3.5L automatique</h1>',
            "https://example.test/tacoma-double",
        )
        access_cab = monitor.extract_listing_metadata(
            '<h1>2022 Toyota Tacoma SR5 Access Cab 4x4 V6 3.5L automatique</h1>',
            "https://example.test/tacoma-access",
        )
        self.assertEqual(double_cab["cab_class"], "double_cab")
        self.assertEqual(double_cab["model"], "Tacoma")
        self.assertEqual(double_cab["transmission"], "automatic")
        self.assertEqual(access_cab["cab_class"], "access_cab")

    def test_recognizes_additional_pickup_models(self):
        self.assertEqual(monitor.infer_vehicle_identity("2017 Honda Ridgeline Crew Cab")["model"], "Ridgeline")
        self.assertEqual(monitor.infer_vehicle_identity("2021 Ford Ranger SuperCrew")["make"], "Ford")

    def test_fetch_marks_sold_page_unavailable(self):
        result = monitor.fetch_listing(
            "https://example.test/sold",
            1,
            opener=lambda *_args, **_kwargs: FakeResponse("Ce véhicule a été vendu"),
        )
        self.assertEqual(result["status"], "unavailable")

    def test_404_is_unavailable(self):
        def opener(*_args, **_kwargs):
            raise HTTPError("https://example.test", 404, "not found", {}, io.BytesIO())

        self.assertEqual(monitor.fetch_listing("https://example.test", 1, opener)["status"], "unavailable")

    def test_403_is_fetch_error_not_unavailable(self):
        def opener(*_args, **_kwargs):
            raise HTTPError("https://example.test", 403, "forbidden", {}, io.BytesIO())

        result = monitor.fetch_listing("https://example.test", 1, opener)
        self.assertEqual(result["status"], "fetch_error")

    def test_network_error_is_fetch_error(self):
        def opener(*_args, **_kwargs):
            raise URLError("timeout")

        self.assertEqual(monitor.fetch_listing("https://example.test", 1, opener)["status"], "fetch_error")

    def test_classifies_price_changes(self):
        reference = {"price": 33000}
        self.assertEqual(monitor.classify(reference, {"status": "active", "price": 32000}), "price_down")
        self.assertEqual(monitor.classify(reference, {"status": "active", "price": 34000}), "price_up")
        self.assertEqual(monitor.classify(reference, {"status": "active", "price": 33000}), "unchanged")

    def test_summary_warns_about_read_errors(self):
        report = {
            "generated_at": "2026-08-05T00:00:00+00:00",
            "reference_checked_at": "2026-08-04",
            "counts": {"unchanged": 0, "price_down": 0, "price_up": 0, "unavailable": 0, "fetch_error": 1, "unknown": 0},
            "listings": [{
                "name": "Test",
                "change": "fetch_error",
                "current": {"price": None, "error": "HTTP 403"},
                "price_delta": None,
            }],
        }
        summary = monitor.format_summary(report)
        self.assertIn("ERREUR DE LECTURE", summary)
        self.assertIn("n'est jamais assimilé", summary)


if __name__ == "__main__":
    unittest.main()
