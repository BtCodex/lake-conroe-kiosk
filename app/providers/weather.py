"""Open-Meteo forecasts for Walden; every displayed value comes from the model.

Open-Meteo is not a local observation station. Timestamps below are valid model
times, deliberately accompanied by ``measurement_type=modeled``.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.network import get_json

API_URL = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo · modeled weather"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _iso(epoch: Any) -> str | None:
    value = _number(epoch)
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _array(section: dict, name: str, length: int) -> list:
    """Nulls are legitimate missing measurements; truncated arrays are not."""
    result = section.get(name)
    if not isinstance(result, list) or len(result) != length:
        raise ValueError(f"Open-Meteo returned an invalid {name} series")
    return result


def _check_response(data: Any) -> dict:
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError("Open-Meteo returned an invalid/error response")
    return data


def normalize_weather(data: dict, *, now: datetime | None = None) -> dict:
    """Normalize only real provider values; never fill gaps with sample data."""
    _check_response(data)
    current, hourly = data.get("current"), data.get("hourly")
    if not isinstance(current, dict) or not isinstance(hourly, dict):
        raise ValueError("Open-Meteo response is missing current/hourly data")
    observed_at = _iso(current.get("time"))
    if observed_at is None:
        raise ValueError("Open-Meteo current valid time is missing")
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise ValueError("Open-Meteo hourly times are missing")
    count = len(times)
    arrays = {name: _array(hourly, name, count) for name in (
        "temperature_2m", "precipitation_probability", "weather_code", "is_day", "uv_index"
    )}
    valid_times = [_number(value) for value in times]
    if any(value is None or _iso(value) is None for value in valid_times):
        raise ValueError("Open-Meteo hourly valid time is malformed")
    if any(b <= a for a, b in zip(valid_times, valid_times[1:])):
        raise ValueError("Open-Meteo hourly times are not increasing")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("Clock must be timezone-aware")
    epoch = clock.timestamp()
    next_indices = [i for i, value in enumerate(valid_times) if value > epoch][:6]
    if not next_indices:
        raise ValueError("Open-Meteo returned no upcoming hourly forecast")
    # UV is an hourly modeled value, so expose its own valid time.
    past_indices = [i for i, value in enumerate(valid_times) if value <= epoch]
    uv_index = past_indices[-1] if past_indices else None
    result_current = {
        "temperature_f": _number(current.get("temperature_2m")),
        "apparent_temperature_f": _number(current.get("apparent_temperature")),
        "relative_humidity_pct": _number(current.get("relative_humidity_2m")),
        "wind_speed_mph": _number(current.get("wind_speed_10m")),
        "wind_direction_deg": _number(current.get("wind_direction_10m")),
        "pressure_hpa": _number(current.get("surface_pressure")),
        "pressure_reference": "surface",
        "uv_index": _number(arrays["uv_index"][uv_index]) if uv_index is not None else None,
        "uv_valid_at": _iso(times[uv_index]) if uv_index is not None else None,
        "weather_code": _number(current.get("weather_code")),
        "is_day": bool(current["is_day"]) if current.get("is_day") in (0, 1) else None,
        "observed_at": observed_at,
        "valid_at": observed_at,
        "measurement_type": "modeled",
    }
    # A structurally valid response containing no weather is still a failed fetch.
    if result_current["temperature_f"] is None and result_current["weather_code"] is None:
        raise ValueError("Open-Meteo returned no usable current weather")
    return {
        "source": SOURCE,
        "source_url": "https://open-meteo.com/",
        "measurement_type": "modeled",
        "current": result_current,
        "hourly": [{
            "time": _iso(times[i]),
            "temperature_f": _number(arrays["temperature_2m"][i]),
            "precipitation_probability_pct": _number(arrays["precipitation_probability"][i]),
            "weather_code": _number(arrays["weather_code"][i]),
            "is_day": bool(arrays["is_day"][i]) if arrays["is_day"][i] in (0, 1) else None,
        } for i in next_indices],
    }


def normalize_forecast(data: dict, *, timezone_name: str = "America/Chicago") -> dict:
    _check_response(data)
    daily = data.get("daily")
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list) or not daily["time"]:
        raise ValueError("Open-Meteo daily forecast is missing")
    count = len(daily["time"])
    arrays = {name: _array(daily, name, count) for name in (
        "temperature_2m_max", "temperature_2m_min", "precipitation_probability_max",
        "weather_code", "sunrise", "sunset"
    )}
    zone = ZoneInfo(timezone_name)
    normalized = []
    for i, value in enumerate(daily["time"][:3]):
        if _iso(value) is None:
            raise ValueError("Open-Meteo daily date is invalid")
        date = datetime.fromtimestamp(float(value), zone).date().isoformat()
        normalized.append({
            "date": date,
            "temperature_max_f": _number(arrays["temperature_2m_max"][i]),
            "temperature_min_f": _number(arrays["temperature_2m_min"][i]),
            "precipitation_probability_pct": _number(arrays["precipitation_probability_max"][i]),
            "weather_code": _number(arrays["weather_code"][i]),
            "sunrise": _iso(arrays["sunrise"][i]),
            "sunset": _iso(arrays["sunset"][i]),
        })
    return {"source": SOURCE, "source_url": "https://open-meteo.com/", "measurement_type": "modeled", "daily": normalized}


def _params(config: dict) -> dict:
    provider = config.get("weather", {}).get("provider", "open-meteo")
    if provider != "open-meteo":
        raise ValueError(f"Unsupported weather provider: {provider}; supported: open-meteo")
    location = config["location"]
    return {
        "latitude": location["latitude"], "longitude": location["longitude"],
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "timezone": config.get("timezone", "America/Chicago"), "timeformat": "unixtime",
        "forecast_days": 3,
    }


async def fetch_weather(config: dict, client: httpx.AsyncClient) -> dict:
    params = _params(config)
    params.update({
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,weather_code,surface_pressure,wind_speed_10m,wind_direction_10m",
        "hourly": "temperature_2m,precipitation_probability,weather_code,is_day,uv_index",
    })
    return normalize_weather(await get_json(client, API_URL, params=params))


async def fetch_forecast(config: dict, client: httpx.AsyncClient) -> dict:
    params = _params(config)
    params["daily"] = "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max"
    return normalize_forecast(await get_json(client, API_URL, params=params), timezone_name=config.get("timezone", "America/Chicago"))
