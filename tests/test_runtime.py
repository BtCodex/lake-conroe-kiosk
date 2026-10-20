"""Runtime behavior using temporary caches and synthetic providers; no live HTTP."""
from __future__ import annotations

import copy
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.cache import SourceManager, age_seconds
from app.config import DEFAULTS, load_config, public_config, validate
from app.network import get_json


async def no_loop(self, name):
    """Suppress background polling so each test drives exact refresh attempts."""
    return None


class CacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.config = copy.deepcopy(DEFAULTS)

    def manager(self, name, provider):
        return SourceManager(self.config, self.path, {name: provider})

    async def test_success_persists_and_reload_uses_last_good_cache(self):
        payload = {"source": "SYNTHETIC TEST", "current": {"temperature_f": 0}}
        provider = AsyncMock(return_value=payload)
        original = self.manager("weather", provider)
        self.assertTrue(await original.refresh("weather"))
        first = original.snapshot()["weather"]
        self.assertEqual(first["status"], "live")
        saved = json.loads((self.path / "weather.json").read_text())
        self.assertEqual(saved["data"], payload)
        restored = self.manager("weather", AsyncMock(side_effect=RuntimeError("offline")))
        with patch.object(SourceManager, "_loop", new=no_loop):
            await restored.start()
            try:
                state = restored.snapshot()["weather"]
                self.assertEqual(state["data"], payload)
                self.assertEqual(state["last_success_at"], first["last_success_at"])
                self.assertEqual(state["status"], "live")
            finally:
                await restored.stop()
        self.assertEqual(provider.await_count, 1)

    async def test_failed_refresh_preserves_data_and_success_timestamp_as_stale(self):
        provider = AsyncMock(side_effect=[{"current": {"temperature_f": 71}}, OSError("test offline")])
        manager = self.manager("weather", provider)
        self.assertTrue(await manager.refresh("weather"))
        initial = manager.snapshot()["weather"]
        self.assertFalse(await manager.refresh("weather"))
        failed = manager.snapshot()["weather"]
        self.assertEqual(failed["status"], "stale")
        self.assertEqual(failed["data"], initial["data"])
        self.assertEqual(failed["last_success_at"], initial["last_success_at"])
        self.assertIn("test offline", failed["error"])
        self.assertFalse(failed["refreshing"])

    async def test_initial_alert_fetch_failure_is_unavailable_never_all_clear(self):
        manager = self.manager("alerts", AsyncMock(side_effect=httpx.ConnectError("test offline")))
        self.assertFalse(await manager.refresh("alerts"))
        state = manager.snapshot()["alerts"]
        self.assertEqual(state["status"], "unavailable")
        self.assertIsNone(state["data"])
        self.assertIsNone(state["last_success_at"])
        self.assertIn("test offline", state["error"])

    async def test_invalid_json_provider_result_cannot_replace_last_good_data(self):
        manager = self.manager("weather", AsyncMock(side_effect=[
            {"current": {"temperature_f": 71}},
            {"current": {"temperature_f": float("nan")}},
        ]))
        self.assertTrue(await manager.refresh("weather"))
        before = manager.snapshot()["weather"]
        persisted = (self.path / "weather.json").read_text()
        self.assertFalse(await manager.refresh("weather"))
        after = manager.snapshot()["weather"]
        self.assertEqual(after["data"], before["data"])
        self.assertEqual(after["last_success_at"], before["last_success_at"])
        self.assertEqual(after["status"], "stale")
        self.assertEqual((self.path / "weather.json").read_text(), persisted)

    async def test_failed_alert_refresh_keeps_prior_all_clear_explicitly_stale(self):
        manager = self.manager("alerts", AsyncMock(side_effect=[{"alerts": []}, RuntimeError("NWS unavailable")]))
        self.assertTrue(await manager.refresh("alerts"))
        self.assertFalse(await manager.refresh("alerts"))
        state = manager.snapshot()["alerts"]
        self.assertEqual(state["data"]["alerts"], [])
        self.assertEqual(state["status"], "stale")
        self.assertIsNotNone(state["error"])

    async def test_lake_retains_each_last_observation_when_partial_fetch_succeeds(self):
        observation = "2026-10-20T15:00:00Z"
        old = {"measurements": {
            "elevation_ft": {"value": 201.01, "unit": "ft", "observed_at": observation, "datum": "NGVD29"},
            "outflow_cfs": {"value": 0, "unit": "CFS", "observed_at": observation},
        }}
        new = {"measurements": {
            "elevation_ft": {"value": None, "unit": "ft", "observed_at": None},
            "water_temperature_f": {"value": 77, "observed_at": "2026-10-20T15:03:00Z"},
        }}
        manager = self.manager("lake", AsyncMock(side_effect=[old, new]))
        self.assertTrue(await manager.refresh("lake"))
        self.assertTrue(await manager.refresh("lake"))
        readings = manager.snapshot()["lake"]["data"]["measurements"]
        self.assertEqual(readings["elevation_ft"]["value"], 201.01)
        self.assertEqual(readings["elevation_ft"]["observed_at"], observation)
        self.assertTrue(readings["elevation_ft"]["stale"])
        self.assertEqual(readings["outflow_cfs"]["value"], 0)
        self.assertTrue(readings["outflow_cfs"]["stale"])
        self.assertEqual(readings["water_temperature_f"]["value"], 77)
        self.assertNotIn("stale", old["measurements"]["elevation_ft"])

    async def test_corrupt_saved_cache_is_ignored(self):
        (self.path / "weather.json").write_text("not json")
        manager = self.manager("weather", AsyncMock(return_value={"current": {}}))
        with patch.object(SourceManager, "_loop", new=no_loop):
            await manager.start()
            try:
                self.assertIsNone(manager.snapshot()["weather"]["data"])
            finally:
                await manager.stop()

    async def test_numeric_and_http_date_retry_after_set_delay_then_success_resets_it(self):
        fixed_now = datetime.now(timezone.utc).replace(microsecond=0)
        future_date = format_datetime(fixed_now + timedelta(seconds=900), usegmt=True)
        for header in ("900", future_date):
            with self.subTest(retry_after=header):
                request = httpx.Request("GET", "https://test.invalid/weather")
                response = httpx.Response(429, headers={"Retry-After": header}, request=request)
                error = httpx.HTTPStatusError("synthetic rate limit", request=request, response=response)
                manager = self.manager("weather", AsyncMock(side_effect=[
                    error, {"current": {"temperature_f": 71}},
                ]))
                with patch("app.cache.datetime") as clock:
                    clock.now.return_value = fixed_now
                    self.assertFalse(await manager.refresh("weather"))
                    self.assertEqual(manager.sources["weather"].retry_after_seconds, 900)
                    self.assertTrue(await manager.refresh("weather"))
                    self.assertEqual(manager.sources["weather"].retry_after_seconds, 0)
                self.assertEqual(manager.snapshot()["weather"]["status"], "live")

    async def test_polling_loop_waits_for_longer_upstream_retry_after_without_real_sleep(self):
        request = httpx.Request("GET", "https://test.invalid/weather")
        response = httpx.Response(503, headers={"Retry-After": "900"}, request=request)
        error = httpx.HTTPStatusError("synthetic unavailable", request=request, response=response)
        manager = self.manager("weather", AsyncMock(side_effect=error))
        # Cancellation at the first mocked sleep ends the continuous loop.
        with patch("app.cache.asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await manager._loop("weather")
            sleep.assert_awaited_once_with(900)
        self.assertGreater(manager.sources["weather"].retry_after_seconds, manager.sources["weather"].interval)

    def test_elapsed_cache_is_stale_even_without_error(self):
        manager = self.manager("weather", AsyncMock())
        source = manager.sources["weather"]
        source.data = {"current": {"temperature_f": 70}}
        source.last_success_at = (datetime.now(timezone.utc) - timedelta(seconds=601)).isoformat()
        self.assertEqual(manager.snapshot()["weather"]["status"], "stale")
        self.assertIsNone(age_seconds("not a timestamp"))
        self.assertIsNone(age_seconds("2026-10-20T12:00:00"))


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_403_is_not_retried(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(403, json={"error": "denied"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.network.asyncio.sleep", new_callable=AsyncMock) as delay:
                with self.assertRaises(httpx.HTTPStatusError):
                    await get_json(client, "https://test.invalid/denied")
                self.assertEqual(len(calls), 1)
                delay.assert_not_awaited()

    async def test_transient_503_retries_once_then_returns_json(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(503 if len(calls) == 1 else 200, json={"attempt": len(calls)})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.network.asyncio.sleep", new_callable=AsyncMock) as delay:
                result = await get_json(client, "https://test.invalid/recover", params={"point": "30,-95"})
                self.assertEqual(result, {"attempt": 2})
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[-1].url.params["point"], "30,-95")
                delay.assert_awaited_once_with(1.0)

    async def test_retry_after_is_respected_by_not_retrying_early(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(429, headers={"Retry-After": "60"}, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.network.asyncio.sleep", new_callable=AsyncMock) as delay:
                with self.assertRaises(httpx.HTTPStatusError):
                    await get_json(client, "https://test.invalid/limited")
                self.assertEqual(len(calls), 1)
                delay.assert_not_awaited()

    async def test_persistent_timeout_stops_after_two_attempts(self):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.network.asyncio.sleep", new_callable=AsyncMock):
                with self.assertRaises(httpx.ReadTimeout):
                    await get_json(client, "https://test.invalid/timeout")
                self.assertEqual(len(calls), 2)


class ConfigTests(unittest.TestCase):
    def test_partial_file_merges_without_mutating_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"title": "Test display", "server": {"port": 8099}}))
            config = load_config(path)
        self.assertEqual(config["title"], "Test display")
        self.assertEqual(config["server"]["port"], 8099)
        self.assertEqual(config["location"]["latitude"], DEFAULTS["location"]["latitude"])
        self.assertEqual(DEFAULTS["server"]["port"], 8080)
        public = public_config(config)
        self.assertNotIn("server", public)
        public["location"]["latitude"] = 0
        self.assertNotEqual(config["location"]["latitude"], 0)

    def test_invalid_coordinates_ports_and_units_rejected(self):
        invalid = [("location", "latitude", True), ("location", "longitude", 181),
                   ("location", "latitude", float("nan")), ("server", "port", 65536),
                   ("server", "port", 0), ("server", "port", True),
                   ("polling", "weather", 1), ("polling", "alerts", float("inf")),
                   ("camera", "retry_seconds", float("nan")),
                   ("camera", "image_refresh_seconds", float("inf"))]
        for section, key, value in invalid:
            with self.subTest(section=section, key=key, value=value):
                config = copy.deepcopy(DEFAULTS)
                config[section][key] = value
                with self.assertRaises(ValueError):
                    validate(config)
        config = copy.deepcopy(DEFAULTS)
        config["temperature_unit"] = "kelvin"
        with self.assertRaises(ValueError):
            validate(config)

    def test_missing_explicit_file_and_non_object_json_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                load_config(path)
            path.write_text("[]")
            with self.assertRaises(ValueError):
                load_config(path)


class EndpointTests(unittest.TestCase):
    def test_dashboard_source_health_config_and_static_routes(self):
        # Imported here so provider module discovery finishes independently.
        from app.main import create_app
        fixtures = {
            "weather": {"source": "SYNTHETIC TEST", "current": {"temperature_f": 71}},
            "forecast": {"daily": []}, "lake": {"measurements": {}},
            "alerts": {"alerts": []}, "camera": {"status": "configured", "live": False},
        }
        providers = {name: AsyncMock(return_value=data) for name, data in fixtures.items()}
        with tempfile.TemporaryDirectory() as directory, patch.object(SourceManager, "_loop", new=no_loop):
            application = create_app(config=copy.deepcopy(DEFAULTS), providers=providers, cache_dir=Path(directory))
            with TestClient(application) as client:
                for name in fixtures:
                    self.assertTrue(client.portal.call(application.state.manager.refresh, name))
                response = client.get("/api/dashboard")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                self.assertEqual(response.json()["sources"]["weather"]["data"], fixtures["weather"])
                config = client.get("/api/config").json()
                self.assertEqual(config["timezone"], "America/Chicago")
                self.assertNotIn("server", config)
                self.assertEqual(client.get("/api/alerts").json()["status"], "live")
                health = client.get("/api/health").json()
                self.assertEqual(health["application"], "lake-conroe-live")
                self.assertEqual(health["status"], "ok")
                self.assertNotIn("data", health["sources"]["weather"])
                self.assertEqual(client.get("/api/unknown").status_code, 404)
                self.assertEqual(client.get("/static/camera.js").status_code, 200)
                self.assertEqual(client.get("/").status_code, 200)
                # Losing NWS after an all-clear must change service health.
                providers["alerts"].side_effect = httpx.ConnectError("synthetic offline")
                self.assertFalse(client.portal.call(application.state.manager.refresh, "alerts"))
                self.assertEqual(client.get("/api/alerts").json()["status"], "stale")
                self.assertEqual(client.get("/api/health").json()["status"], "degraded")
        for provider in providers.values():
            provider.assert_awaited()


if __name__ == "__main__":
    unittest.main()
