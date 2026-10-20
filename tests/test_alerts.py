"""NWS alert normalization; all alerts here are synthetic test fixtures."""
import unittest
from app.providers.alerts import normalize_alerts


class AlertTests(unittest.TestCase):
    def test_empty_valid_collection_means_no_alerts(self):
        self.assertEqual(normalize_alerts({"type": "FeatureCollection", "features": []})["alerts"], [])

    def test_error_response_never_becomes_no_alerts(self):
        for response in ({}, {"status": 503}, {"type": "FeatureCollection", "features": None}):
            with self.assertRaises(ValueError):
                normalize_alerts(response)

    def test_severity_order_and_identity(self):
        features = [{"id": f"https://api.weather.gov/alerts/test-{i}", "properties": {
            "id": str(i), "event": event, "severity": severity, "urgency": "Immediate",
            "headline": "SYNTHETIC TEST ONLY", "expires": "2026-10-21T00:00:00Z",
        }} for i, event, severity in [(1, "Wind Advisory", "Minor"), (2, "Tornado Warning", "Extreme")]]
        result = normalize_alerts({"type": "FeatureCollection", "features": features + [features[0]]})
        self.assertEqual(len(result["alerts"]), 2)
        self.assertEqual(result["alerts"][0]["event"], "Tornado Warning")
        self.assertEqual(result["alerts"][0]["expires"], "2026-10-21T00:00:00Z")
        self.assertIn("api.weather.gov", result["alerts"][0]["url"])

    def test_malformed_feature_raises(self):
        with self.assertRaises(ValueError):
            normalize_alerts({"type": "FeatureCollection", "features": [{"properties": {}}]})


if __name__ == "__main__":
    unittest.main()
