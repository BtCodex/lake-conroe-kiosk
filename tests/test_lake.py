"""Clearly labeled synthetic fixtures; none are production observations."""
import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import httpx

from app.providers.sjra import fetch_lake, parse_sjra_html
from app.providers.usgs import celsius_to_fahrenheit, cms_to_cfs, meters_to_feet, parse_usgs


def series(code, unit, readings, no_data=-999999):
    return {
        'variable': {'variableCode': [{'value': code}], 'unit': {'unitCode': unit}, 'noDataValue': no_data},
        'values': [{'value': [{'value': str(value), 'dateTime': stamp, 'qualifiers': ['P']} for value, stamp in readings]}],
    }


class LakeParserTests(unittest.TestCase):
    def test_explicit_published_lake_level_and_datum(self):
        html = '<h1>Lake Conroe Level</h1><p>201.23 ft NGVD 1929</p><p>Last Updated: 10/20/2025 03:15 PM</p>'
        result = parse_sjra_html(html, 'elevation_ft')
        self.assertEqual(result['value'], 201.23)
        self.assertEqual(result['datum'], 'NGVD29')
        self.assertEqual(result['observed_at'], '2025-10-20T20:15:00+00:00')

    def test_missing_timestamp_is_never_fabricated(self):
        result = parse_sjra_html('<p>Lake Level: 200.9 feet</p>', 'elevation_ft')
        self.assertIsNone(result['observed_at'])
        self.assertEqual(result['datum'], 'unknown')

    def test_zero_release_is_valid(self):
        result = parse_sjra_html('<p>Lake Release: 0 CFS</p><p>As of 2025-01-12T08:00:00-06:00</p>', 'outflow_cfs')
        self.assertEqual(result['value'], 0)
        self.assertEqual(result['observed_at'], '2025-01-12T14:00:00+00:00')

    def test_water_temperature_and_html_entities(self):
        result = parse_sjra_html('<h2>Water Temperature</h2><div>81.7 &deg;F</div>', 'water_temperature_f')
        self.assertEqual(result['value'], 81.7)

    def test_compass_direction(self):
        result = parse_sjra_html('<div>Wind Direction: NNE</div>', 'wind_direction_deg')
        self.assertEqual(result['value'], 22.5)

    def test_does_not_parse_chart_javascript_as_current_reading(self):
        with self.assertRaises(ValueError):
            parse_sjra_html('<h1>Lake Level</h1><script>var old="201 ft";</script>', 'elevation_ft')

    def test_rejects_ambiguous_or_wrong_units(self):
        for html in ('Lake Level 201 ft Lake Level 199 ft', 'Lake Level 61.2 meters', 'Lake Level unavailable copyright 2025'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                parse_sjra_html(html, 'elevation_ft')

    def test_conflicting_datums_stay_unknown(self):
        result = parse_sjra_html('Lake Level 201 ft (NGVD29) reference: NAVD88', 'elevation_ft')
        self.assertEqual(result['datum'], 'unknown')

    def test_conservation_pool_reference_is_not_measured_level(self):
        with self.assertRaises(ValueError):
            parse_sjra_html('Lake Level: Conservation pool 201 feet Current reading unavailable', 'elevation_ft')

    def test_ambiguous_local_dst_hour_is_not_guessed(self):
        result = parse_sjra_html('Lake Level: 201 feet Last updated: 11/02/2025 01:30 AM', 'elevation_ft')
        self.assertIsNone(result['observed_at'])

    def test_does_not_use_failed_response_numbers(self):
        with self.assertRaises(ValueError):
            parse_sjra_html('Access Denied Lake Level 201 feet', 'elevation_ft')


class USGSTests(unittest.TestCase):
    def test_conversions(self):
        self.assertEqual(celsius_to_fahrenheit(0), 32)
        self.assertEqual(celsius_to_fahrenheit(100), 212)
        self.assertAlmostEqual(meters_to_feet(0.3048), 1)
        self.assertAlmostEqual(cms_to_cfs(0.028316846592), 1)

    def test_latest_finite_valid_reading_and_explicit_datum(self):
        payload = {'value': {'timeSeries': [series('62614', 'ft', [(-999999, '2025-01-01T12:00:00Z'), (200.1, '2025-01-01T10:00:00Z'), (201.2, '2025-01-01T11:00:00Z')])]}}
        record = parse_usgs(payload)['elevation_ft']
        self.assertEqual(record['value'], 201.2)
        self.assertEqual(record['datum'], 'NGVD29')
        self.assertEqual(record['observed_at'], '2025-01-01T11:00:00+00:00')
        self.assertEqual(record['qualifiers'], ['P'])

    def test_navd_is_retained_without_conversion(self):
        payload = {'value': {'timeSeries': [series('62615', 'ft', [(201.1, '2025-01-01T11:00:00Z')])]}}
        self.assertEqual(parse_usgs(payload)['elevation_ft']['datum'], 'NAVD88')

    def test_water_temperature_conversion(self):
        payload = {'value': {'timeSeries': [series('00010', 'deg C', [(25, '2025-01-01T11:00:00Z')])]}}
        self.assertEqual(parse_usgs(payload)['water_temperature_f']['value'], 77)

    def test_gage_height_is_not_lake_elevation_and_rain_is_not_assumed(self):
        payload = {'value': {'timeSeries': [series('00065', 'ft', [(201, '2025-01-01T11:00:00Z')]), series('00045', 'in', [(5.2, '2025-01-01T11:00:00Z')])]}}
        self.assertEqual(parse_usgs(payload), {})

    def test_flow_needs_explicit_outflow_configuration(self):
        payload = {'value': {'timeSeries': [series('00060', 'ft3/s', [(42, '2025-01-01T11:00:00Z')])]}}
        self.assertEqual(parse_usgs(payload), {})
        self.assertEqual(parse_usgs(payload, discharge_is_outflow=True)['outflow_cfs']['value'], 42)

    def test_rejects_future_nodata_nan_and_naive_readings(self):
        payload = {'value': {'timeSeries': [series('62614', 'ft', [('NaN', '2025-01-01T11:00:00Z'), (-999999, '2025-01-01T11:00:00Z'), (201, '2099-01-01T11:00:00Z'), (202, '2025-01-01T11:00:00')])]}}
        self.assertEqual(parse_usgs(payload), {})


class LakeFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_failures_keep_measurements_and_report_status(self):
        async def text(client, url, params=None):
            if url.endswith('lake-level-index.php'):
                return 'Lake Level: 201.0 feet NGVD29 Last updated: 2025-01-01T11:00:00Z'
            raise ValueError('Synthetic fixture failure')
        async def usgs(config, client):
            return {'water_temperature_f': {'value': 77, 'unit': '°F', 'source': 'USGS NWIS', 'observed_at': '2025-01-01T11:00:00+00:00'}}
        async with httpx.AsyncClient() as client:
            with patch('app.providers.sjra.get_text', text), patch('app.providers.sjra.fetch_usgs', usgs):
                result = await fetch_lake({}, client)
        self.assertEqual(result['measurements']['elevation_ft']['value'], 201)
        self.assertEqual(result['measurements']['water_temperature_f']['value'], 77)
        self.assertIsNone(result['measurements']['rainfall_24h_in'])
        self.assertEqual(result['source_status']['sjra']['status'], 'partial')
        self.assertEqual(result['source_status']['onerain']['status'], 'unverified')

    async def test_total_failure_raises_for_root_cache_retention(self):
        async def fail(*args, **kwargs):
            raise ValueError('Synthetic offline fixture')
        async with httpx.AsyncClient() as client:
            with patch('app.providers.sjra.get_text', fail), patch('app.providers.sjra.fetch_usgs', fail):
                with self.assertRaisesRegex(ValueError, 'No confirmed lake readings'):
                    await fetch_lake({}, client)


if __name__ == '__main__':
    unittest.main()
