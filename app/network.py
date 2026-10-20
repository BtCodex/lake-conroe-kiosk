"""Bounded upstream requests with normal TLS verification and retry backoff."""
from __future__ import annotations

import asyncio
from typing import Any
import httpx

USER_AGENT = "LakeConroeLive/1.0 (self-hosted local weather display; github.com/BtCodex/lake-conroe-kiosk)"


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> httpx.Response:
    for attempt in range(2):
        try:
            response = await client.get(url, params=params, follow_redirects=True)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if attempt or exc.response.status_code not in (429, 500, 502, 503, 504):
                raise
            # Never hammer a rate-limited endpoint. A longer Retry-After is left to the polling loop.
            if exc.response.headers.get("Retry-After"):
                raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            if attempt:
                raise
        await asyncio.sleep(1.0)
    raise RuntimeError("Request exhausted")


async def get_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> Any:
    response = await _get(client, url, params)
    return response.json()


async def get_text(client: httpx.AsyncClient, url: str, params: dict | None = None) -> str:
    return (await _get(client, url, params)).text
