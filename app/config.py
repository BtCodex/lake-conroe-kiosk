"""Validated local configuration. No credentials are needed by default."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {
    "title": "LAKE CONROE",
    "location": {"latitude": 30.402, "longitude": -95.608, "label": "Walden • Montgomery, Texas"},
    "timezone": "America/Chicago",
    "temperature_unit": "fahrenheit",
    "panels": {"weather": True, "hourly": True, "forecast": True, "lake": True},
    "server": {"host": "127.0.0.1", "port": 8080, "cache_dir": ".cache/lake-conroe-live"},
    "weather": {"provider": "open-meteo"},
    "lake": {"usgs_station": "08067600", "conservation_pool_ft": 201.0, "conservation_pool_datum": "NGVD29"},
    "camera": {
        "provider": "youtube", "url": "https://www.youtube.com/embed/UqrwUKSkMEE",
        "source_page": "https://lakeconroe.com/live-web-cams-on-lake-conroe/live-web-cam-abc-13-news/",
        "discover_from_source": True, "alternative_url": None,
        "attribution": "ABC13 / LakeConroe.com", "retry_seconds": 30, "image_refresh_seconds": 60,
    },
    "polling": {"weather": 300, "forecast": 1800, "lake": 180, "alerts": 120, "camera": 1800},
}


def merge(base: dict, updates: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> dict:
    chosen = path or os.environ.get("LAKE_CONROE_CONFIG")
    if chosen:
        config_path = Path(chosen).expanduser()
        if not config_path.is_absolute():
            config_path = ROOT / config_path
    else:
        config_path = ROOT / "config/settings.local.json"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as handle:
            overrides = json.load(handle)
        if not isinstance(overrides, dict):
            raise ValueError("Configuration must be a JSON object")
    elif chosen:
        raise FileNotFoundError(f"Configuration file does not exist: {config_path}")
    else:
        overrides = {}
    config = merge(DEFAULTS, overrides)
    validate(config)
    return config


def validate(config: dict) -> None:
    ZoneInfo(config["timezone"])
    for name, bound in (("latitude", 90), ("longitude", 180)):
        value = config["location"][name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not -bound <= value <= bound:
            raise ValueError(f"Invalid location.{name}")
    port = config["server"]["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("server.port must be between 1 and 65535")
    if config["temperature_unit"] not in ("fahrenheit", "celsius"):
        raise ValueError("temperature_unit must be fahrenheit or celsius")
    if config["weather"]["provider"] != "open-meteo":
        raise ValueError("Supported weather.provider is open-meteo; alerts always use NWS")
    for name, seconds in config["polling"].items():
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 60:
            raise ValueError(f"polling.{name} must be at least 60 seconds")
    for name in ("retry_seconds", "image_refresh_seconds"):
        value = config["camera"][name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 10:
            raise ValueError(f"camera.{name} must be at least 10 seconds")


def public_config(config: dict) -> dict:
    return {key: copy.deepcopy(config[key]) for key in ("title", "location", "timezone", "temperature_unit", "panels", "camera", "polling", "lake")}
