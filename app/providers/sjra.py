"""SJRA published-reading adapters with conservative, unit-aware parsing.

Cloud verification initially received proxy 403s for levels.sjra.info and
sanjacinto.onerain.com. The parser accepts explicit labeled measurements and
units, rather than treating the first number in a page as a reading. Embedded
charts without readable measurements remain unavailable. OneRain is not
scraped or called as an undocumented JSON API.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import math
import re
from zoneinfo import ZoneInfo

import httpx

from app.network import get_text
from app.providers.usgs import fetch_usgs

BASE = 'https://levels.sjra.info/'
# Endpoint, human-readable label patterns, mandatory published units, bounds.
SPECS = {
    'elevation_ft': ('lake-level-index.php', r'(?:lake\s+(?:conroe\s+)?(?:level|elevation)|water\s+surface\s+elevation|reservoir\s+elevation)', r'(?:ft\b|feet\b)', 'ft', -100, 1500),
    'water_temperature_f': ('lake-watertemp-index.php', r'(?:lake\s+)?water\s+temp(?:erature)?', r'(?:°\s*f\b|deg(?:rees?)?\.?\s*f\b|fahrenheit\b)', '°F', -50, 160),
    'outflow_cfs': ('lake-release-index.php', r'(?:lake\s+(?:conroe\s+)?release|(?:dam\s+)?outflow|release\s+(?:rate|flow))', r'(?:cfs\b|ft[³3]/s\b|cubic\s+feet\s+per\s+second\b)', 'CFS', 0, 200000),
    'air_temperature_f': ('lake-airtemp-index.php', r'(?:local\s+)?air\s+temp(?:erature)?', r'(?:°\s*f\b|deg(?:rees?)?\.?\s*f\b|fahrenheit\b)', '°F', -100, 160),
    'wind_direction_deg': ('lake-wind-index.php', r'wind\s+(?:direction|bearing)', r'(?:°|deg(?:rees?)?\.?)', '°', 0, 360),
    'wind_speed_mph': ('lake-windspeed-index.php', r'wind\s+(?:speed|velocity)', r'(?:mph\b|mi/?h\b|miles\s+per\s+hour\b)', 'MPH', 0, 250),
}


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        elif tag in ('br', 'p', 'div', 'tr', 'td', 'th', 'h1', 'h2', 'h3', 'span') and not self.hidden:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden:
            self.parts.append(' ')

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


def _text(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def _observation_time(text: str, timezone_name: str) -> str | None:
    """Parse only explicitly labeled observation/update dates, never fetch time."""
    match = re.search(r'(?:last\s+(?:updated?|reading|observation)|updated?|as\s+of|observ(?:ed|ation)(?:\s+at)?|recorded|timestamp)\s*[:=]?\s*(.{10,85})', text, re.I)
    if not match:
        return None
    remainder = match.group(1).strip()
    iso = re.match(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)', remainder)
    parsed = None
    if iso:
        try:
            parsed = datetime.fromisoformat(iso.group(1).replace('Z', '+00:00'))
        except ValueError:
            pass
    if parsed is None:
        # Most legacy telemetry pages use US date and 12-hour local time.
        for pattern, formats in (
            (r'(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)', ('%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y %I:%M %p', '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M')),
            (r'([A-Za-z]+\s+\d{1,2},?\s+\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM))', ('%B %d, %Y %I:%M %p', '%b %d, %Y %I:%M %p', '%B %d %Y %I:%M %p', '%b %d %Y %I:%M %p')),
        ):
            candidate = re.match(pattern, remainder, re.I)
            if not candidate:
                continue
            stamp = re.sub(r'\s+', ' ', candidate.group(1)).strip().upper()
            for fmt in formats:
                try:
                    parsed = datetime.strptime(stamp, fmt)
                    break
                except ValueError:
                    continue
            if parsed:
                break
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        zone = ZoneInfo(timezone_name)
        # An offset-free repeated/skipped DST hour has no unique instant.
        # Keep it unknown rather than guessing which observation was published.
        early = parsed.replace(tzinfo=zone, fold=0)
        late = parsed.replace(tzinfo=zone, fold=1)
        if early.utcoffset() != late.utcoffset():
            return None
        parsed = early
    return parsed.astimezone(timezone.utc).isoformat()


def parse_sjra_html(html: str, measurement: str, *, timezone_name='America/Chicago') -> dict:
    """Extract an explicitly labeled, unit-bearing measurement or reject it.

    Fetch timestamps are never observation timestamps. A published numeric
    reading without a published time keeps observed_at=None for honest display.
    """
    if measurement not in SPECS:
        raise ValueError(f'Unsupported SJRA measurement {measurement}')
    endpoint, label, units, unit, lower, upper = SPECS[measurement]
    text = _text(html)
    if not text or re.search(r'(?i)access\s+denied|cloudflare|captcha', text):
        raise ValueError('SJRA response is empty or an access/error page')
    candidates = []
    # A constrained distance avoids selecting unrelated historical/chart values.
    for heading in re.finditer(label, text, re.I):
        after = text[heading.end():heading.end() + 180]
        # Require the value immediately after the metric label, allowing a
        # short current-reading qualifier. Never consume a conservation-pool
        # reference, chart legend, or historic extrema between label and value.
        prefix = r'^\s*[:=]?\s*(?:(?:current|latest|observed|reading|value)\s*[:=]?\s*)?'
        unit_value = re.search(prefix + r'(-?\d[\d,]*(?:\.\d+)?)\s*' + units, after, re.I)
        if unit_value:
            number = float(unit_value.group(1).replace(',', ''))
            if math.isfinite(number) and lower <= number <= upper:
                candidates.append(number)
        elif measurement == 'wind_direction_deg':
            compass = re.match(r'\s*[:=]?\s*(NNE|ENE|ESE|SSE|SSW|WSW|WNW|NNW|NE|SE|SW|NW|N|E|S|W)\b', after, re.I)
            if compass:
                rose = ('N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW')
                candidates.append(rose.index(compass.group(1).upper()) * 22.5)
    distinct = set(candidates)
    if len(distinct) != 1:
        raise ValueError(f'SJRA {measurement}: no unambiguous labeled reading with expected units')
    record = {
        'value': candidates[0], 'unit': unit,
        'observed_at': _observation_time(text, timezone_name),
        'source': 'San Jacinto River Authority', 'url': BASE + endpoint,
    }
    if measurement == 'elevation_ft':
        ngvd = bool(re.search(r'\bNGVD\s*(?:19)?29\b', text, re.I))
        navd = bool(re.search(r'\bNAVD\s*(?:19)?88\b', text, re.I))
        record['datum'] = 'NGVD29' if ngvd and not navd else 'NAVD88' if navd and not ngvd else 'unknown'
    return record


async def fetch_lake(config: dict, client: httpx.AsyncClient) -> dict:
    """Fetch independently; partial failure preserves other verified readings."""
    measurements = {key: None for key in SPECS}
    measurements['rainfall_24h_in'] = None
    failures = {}
    semaphore = asyncio.Semaphore(3)

    async def one(key, spec):
        try:
            async with semaphore:
                html = await get_text(client, BASE + spec[0])
            measurements[key] = parse_sjra_html(html, key, timezone_name=config.get('timezone', 'America/Chicago'))
        except Exception as error:
            # Cancellation is not caught (CancelledError inherits BaseException).
            failures[key] = f'{type(error).__name__}: {error}'[:300]

    await asyncio.gather(*(one(key, spec) for key, spec in SPECS.items()))
    successful = sum(record is not None for record in measurements.values())
    status = {
        'sjra': {'status': 'ok' if successful == len(SPECS) else 'partial' if successful else 'unavailable', 'errors': failures},
        'onerain': {'status': 'unverified', 'detail': 'No public structured feed has been verified. 24-hour measured rain remains unavailable.'},
    }
    # Use structured USGS data where primary elevation/water temperature is absent.
    if measurements['elevation_ft'] is None or measurements['water_temperature_f'] is None:
        try:
            fallback = await fetch_usgs(config, client)
            for key, record in fallback.items():
                if measurements.get(key) is None:
                    measurements[key] = record
            status['usgs'] = {'status': 'ok' if fallback else 'no_matching_readings'}
        except Exception as error:
            status['usgs'] = {'status': 'unavailable', 'error': f'{type(error).__name__}: {error}'[:300]}
    else:
        status['usgs'] = {'status': 'not_needed'}
    if not any(record is not None for record in measurements.values()):
        raise ValueError('No confirmed lake readings available; SJRA: ' + '; '.join(failures.values())[:500] + '; USGS: ' + str(status['usgs']))
    settings = config.get('lake', {})
    limitations = ['24-hour rainfall is unavailable: no compatible observed interval feed is confirmed.']
    elevation = measurements.get('elevation_ft')
    if elevation and elevation.get('datum') == 'unknown':
        limitations.append('Published elevation datum is unknown; no conservation-pool difference is calculated.')
    if failures:
        limitations.append('Some SJRA measurements are unavailable; check source_status for individual failures.')
    return {
        'source': 'SJRA / USGS', 'measurements': measurements,
        'conservation_pool': {'value_ft': settings.get('conservation_pool_ft', 201.0), 'datum': settings.get('conservation_pool_datum', 'NGVD29'), 'kind': 'reference'},
        'limitations': limitations, 'source_status': status,
    }
