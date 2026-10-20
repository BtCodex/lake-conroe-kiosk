"""Official NWS active alerts for a configured point, with explicit failures."""
from __future__ import annotations

from typing import Any
import httpx

from app.network import get_json

API_URL = "https://api.weather.gov/alerts/active"


def normalize_alerts(data: Any) -> dict:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ValueError("NWS returned an invalid alert collection")
    alerts, seen = [], set()
    for feature in data["features"]:
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
            raise ValueError("NWS returned a malformed alert")
        props = feature["properties"]
        identifier = props.get("id") or feature.get("id")
        if not identifier or not isinstance(props.get("event"), str):
            raise ValueError("NWS alert is missing its identifier/event")
        if identifier in seen:
            continue
        seen.add(identifier)
        alerts.append({
            "id": identifier, "event": props["event"],
            "headline": props.get("headline") or props["event"],
            "severity": props.get("severity", "Unknown"),
            "urgency": props.get("urgency", "Unknown"),
            "description": props.get("description"), "instruction": props.get("instruction"),
            "effective": props.get("effective"), "expires": props.get("expires"),
            "url": feature.get("id") if str(feature.get("id", "")).startswith("https://api.weather.gov/") else "https://www.weather.gov/",
        })
    order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}
    alerts.sort(key=lambda alert: (order.get(alert["severity"], 4), alert["event"]))
    return {
        "source": "National Weather Service", "source_url": "https://www.weather.gov/",
        "alerts": alerts,
    }


async def fetch_alerts(config: dict, client: httpx.AsyncClient) -> dict:
    location = config["location"]
    data = await get_json(client, API_URL, params={"point": f'{location["latitude"]},{location["longitude"]}'})
    return normalize_alerts(data)
