"""Conservative USGS NWIS instantaneous-reading fallback for Lake Conroe.

Only explicit water-surface elevations (62614 NGVD29 / 62615 NAVD88)
are elevations. Gage height (00065) is deliberately not substituted. Rainfall
is not derived from an unspecified cumulative/interval sensor.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

import httpx

from app.network import get_json


def celsius_to_fahrenheit(value: float) -> float:
    return value * 9.0 / 5.0 + 32.0


def meters_to_feet(value: float) -> float:
    return value / 0.3048


def cms_to_cfs(value: float) -> float:
    return value / 0.028316846592


def _number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parse_usgs(payload: dict, *, discharge_is_outflow: bool = False) -> dict:
    """Normalize NWIS JSON, retaining the observation's datum and timestamp."""
    measurements = {}
    series = payload.get('value', {}).get('timeSeries')
    if not isinstance(series, list):
        raise ValueError('USGS response has no timeSeries list')
    for item in series:
        variable = item.get('variable', {})
        codes = variable.get('variableCode', [])
        code = str(codes[0].get('value', '')) if codes else ''
        unit = str(variable.get('unit', {}).get('unitCode', '')).lower().strip()
        nodata = _number(variable.get('noDataValue'))
        datum = None
        transform = lambda v: v
        if code in ('62614', '62615'):
            key, output_unit = 'elevation_ft', 'ft'
            datum = 'NGVD29' if code == '62614' else 'NAVD88'
            if unit in ('m', 'meters', 'metres'):
                transform = meters_to_feet
            elif unit not in ('ft', 'feet'):
                continue
        elif code == '00010':
            key, output_unit = 'water_temperature_f', '°F'
            if unit in ('deg c', 'degc', 'c', '°c'):
                transform = celsius_to_fahrenheit
            elif unit not in ('deg f', 'degf', 'f', '°f'):
                continue
        elif code == '00060' and discharge_is_outflow:
            key, output_unit = 'outflow_cfs', 'CFS'
            if unit in ('m3/s', 'm^3/s'):
                transform = cms_to_cfs
            elif unit not in ('ft3/s', 'ft^3/s', 'cfs'):
                continue
        else:
            continue
        candidates = []
        for group in item.get('values', []):
            for reading in group.get('value', []):
                number = _number(reading.get('value'))
                raw_time = reading.get('dateTime')
                if number is None or number == nodata or not raw_time:
                    continue
                try:
                    observed = datetime.fromisoformat(raw_time.replace('Z', '+00:00'))
                    if observed.tzinfo is None:
                        continue
                    observed = observed.astimezone(timezone.utc)
                    if observed > datetime.now(timezone.utc):
                        continue
                except (ValueError, TypeError):
                    continue
                candidates.append((observed, transform(number), reading.get('qualifiers', [])))
        if not candidates:
            continue
        observed, value, qualifiers = max(candidates, key=lambda candidate: candidate[0])
        current = measurements.get(key)
        # Prefer the freshest reading. Never silently convert between datums.
        if current and current['observed_at'] >= observed.isoformat():
            continue
        record = {
            'value': round(value, 3), 'unit': output_unit,
            'observed_at': observed.isoformat(), 'source': 'USGS NWIS',
            'url': 'https://waterdata.usgs.gov/monitoring-location/USGS-08067600/',
            'qualifiers': qualifiers,
        }
        if datum:
            record['datum'] = datum
        measurements[key] = record
    return measurements


async def fetch_usgs(config: dict, client: httpx.AsyncClient) -> dict:
    settings = config.get('lake', {})
    station = str(settings.get('usgs_station', '08067600'))
    payload = await get_json(client, 'https://waterservices.usgs.gov/nwis/iv/', params={
        'format': 'json', 'sites': station, 'siteStatus': 'all',
        'parameterCd': '62614,62615,00010,00060',
    })
    records = parse_usgs(payload, discharge_is_outflow=bool(settings.get('usgs_discharge_is_outflow', False)))
    for record in records.values():
        record['url'] = f'https://waterdata.usgs.gov/monitoring-location/USGS-{station}/'
    return records
