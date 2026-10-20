"""Synthetic fixtures are used only in these parser tests, never in production."""
import copy
from datetime import datetime, timezone
import unittest

from app.providers.weather import normalize_weather, normalize_forecast, _params


class WeatherTests(unittest.TestCase):
    def setUp(self):
        # 2026-10-20 10:00 CDT, before the DST transition.
        self.base = 1792508400
        self.now = datetime.fromtimestamp(self.base + 900, timezone.utc)
        self.fixture = {
            "current": {"time": self.base, "temperature_2m": 0, "apparent_temperature": 67,
                        "relative_humidity_2m": 0, "wind_speed_10m": 0, "wind_direction_10m": 0,
                        "surface_pressure": 1012, "weather_code": 0, "is_day": 1},
            "hourly": {"time": [self.base + i * 3600 for i in range(8)],
                       "temperature_2m": [70 + i for i in range(8)],
                       "precipitation_probability": [0] * 8, "weather_code": [0] * 8,
                       "is_day": [1] * 8, "uv_index": [2.5] * 8},
        }

    def test_zeroes_and_next_six_hours_preserved(self):
        result = normalize_weather(self.fixture, now=self.now)
        self.assertEqual(result["current"]["temperature_f"], 0)
        self.assertEqual(result["current"]["wind_speed_mph"], 0)
        self.assertEqual(result["current"]["relative_humidity_pct"], 0)
        self.assertEqual(result["current"]["wind_direction_deg"], 0)
        self.assertEqual(result["current"]["uv_index"], 2.5)
        self.assertEqual(len(result["hourly"]), 6)
        self.assertEqual(result["hourly"][0]["temperature_f"], 71)
        self.assertEqual(result["measurement_type"], "modeled")
        self.assertTrue(result["current"]["observed_at"].endswith("Z"))

    def test_missing_readings_stay_missing(self):
        self.fixture["current"]["surface_pressure"] = None
        self.fixture["hourly"]["precipitation_probability"][1] = None
        result = normalize_weather(self.fixture, now=self.now)
        self.assertIsNone(result["current"]["pressure_hpa"])
        self.assertIsNone(result["hourly"][0]["precipitation_probability_pct"])

    def test_rejects_truncated_or_stale_series(self):
        self.fixture["hourly"]["weather_code"].pop()
        with self.assertRaises(ValueError):
            normalize_weather(self.fixture, now=self.now)
        fixture = copy.deepcopy(self.fixture)
        fixture["hourly"]["weather_code"].append(0)
        with self.assertRaisesRegex(ValueError, "upcoming"):
            normalize_weather(fixture, now=datetime.fromtimestamp(self.base + 9 * 3600, timezone.utc))

    def test_nonfinite_data_is_unavailable(self):
        self.fixture["current"]["surface_pressure"] = float("nan")
        self.assertIsNone(normalize_weather(self.fixture, now=self.now)["current"]["pressure_hpa"])

    def test_daily_dates_use_local_timezone_across_dst(self):
        # Successive local midnights on the autumn transition are 25 hours apart.
        daily = {"time": [1793509200, 1793599200, 1793685600],
                 "temperature_2m_max": [80, 79, 78], "temperature_2m_min": [60, 59, 58],
                 "precipitation_probability_max": [0, None, 20], "weather_code": [0, 1, 61],
                 "sunrise": [1793532600, 1793619000, 1793705400],
                 "sunset": [1793572200, 1793658600, 1793745000]}
        result = normalize_forecast({"daily": daily})
        self.assertEqual(len(result["daily"]), 3)
        self.assertIsNone(result["daily"][1]["precipitation_probability_pct"])
        self.assertTrue(result["daily"][0]["sunrise"].endswith("Z"))
        self.assertEqual(result["daily"][0]["date"], "2026-11-01")

    def test_units_and_location_explicit(self):
        params = _params({"location": {"latitude": 30.402, "longitude": -95.608}})
        self.assertEqual(params["latitude"], 30.402)
        self.assertEqual(params["temperature_unit"], "fahrenheit")
        self.assertEqual(params["wind_speed_unit"], "mph")
        self.assertEqual(params["timeformat"], "unixtime")

    def test_unknown_provider_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            _params({"location": {}, "weather": {"provider": "imaginary"}})

    def test_error_payload_is_not_weather(self):
        with self.assertRaises(ValueError):
            normalize_weather({"error": True}, now=self.now)


if __name__ == "__main__":
    unittest.main()
