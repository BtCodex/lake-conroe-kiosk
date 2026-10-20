"""Independent source refreshes and small, atomic on-disk last-good caches."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def age_seconds(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
    except (ValueError, TypeError):
        return None


@dataclass
class Source:
    fetch: Callable[[dict, httpx.AsyncClient], Awaitable[dict]]
    interval: float
    data: dict | None = None
    last_success_at: str | None = None
    last_attempt_at: str | None = None
    error: str | None = None
    refreshing: bool = False
    retry_after_seconds: float = 0


class SourceManager:
    def __init__(self, config: dict, directory: Path, providers: dict):
        self.config = config
        self.directory = directory
        self.sources = {name: Source(fn, config["polling"][name]) for name, fn in providers.items()}
        self.tasks: list[asyncio.Task] = []
        self.client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for name, source in self.sources.items():
            try:
                saved = json.loads((self.directory / f"{name}.json").read_text())
                if isinstance(saved.get("data"), dict) and age_seconds(saved.get("last_success_at")) is not None:
                    source.data = saved["data"]
                    source.last_success_at = saved["last_success_at"]
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                log.warning("Ignoring invalid %s cache: %s", name, exc)
        from .network import USER_AGENT
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(12, connect=6),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9"},
        )
        self.tasks = [asyncio.create_task(self._loop(name), name=f"refresh-{name}") for name in self.sources]

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.client:
            await self.client.aclose()

    async def _loop(self, name: str) -> None:
        failures = 0
        while True:
            ok = await self.refresh(name)
            failures = 0 if ok else failures + 1
            # Failed refreshes are retried with capped exponential backoff, independently per source.
            delay = self.sources[name].interval if ok else min(self.sources[name].interval, 30 * 2 ** min(failures - 1, 6))
            delay = max(delay, self.sources[name].retry_after_seconds)
            await asyncio.sleep(delay)

    async def refresh(self, name: str) -> bool:
        source = self.sources[name]
        if source.refreshing:
            return False
        source.refreshing = True
        source.retry_after_seconds = 0
        source.last_attempt_at = now_iso()
        try:
            result = await source.fetch(self.config, self.client)
            if not isinstance(result, dict):
                raise ValueError("Provider returned invalid data")
            if name == "lake":
                result = self._merge_lake(source.data, result)
            # Validate before replacing last-good state, including the in-memory copy.
            json.dumps(result, allow_nan=False)
            source.data = result
            source.last_success_at = now_iso()
            source.error = None
            payload = {"data": result, "last_success_at": source.last_success_at}
            try:
                await asyncio.to_thread(self._save, name, payload)
            except OSError as exc:
                log.error("Could not persist %s cache: %s", name, exc)
            return True
        except Exception as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                retry_after = exc.response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        try:
                            delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                        except (TypeError, ValueError, OverflowError):
                            delay = 0
                    if math.isfinite(delay):
                        source.retry_after_seconds = max(0, delay)
            source.error = f"{type(exc).__name__}: {str(exc)[:220]}"
            log.warning("%s refresh failed: %s", name, source.error)
            return False
        finally:
            source.refreshing = False

    @staticmethod
    def _merge_lake(old: dict | None, new: dict) -> dict:
        result = copy.deepcopy(new)
        readings = result.setdefault("measurements", {})
        for name, previous in (old or {}).get("measurements", {}).items():
            current = readings.get(name)
            if (not current or current.get("value") is None) and previous and previous.get("value") is not None:
                readings[name] = {**previous, "stale": True}
        return result

    def _save(self, name: str, payload: dict) -> None:
        dest = self.directory / f"{name}.json"
        temp = dest.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
        os.replace(temp, dest)

    def snapshot(self) -> dict:
        result = {}
        for name, source in self.sources.items():
            age = age_seconds(source.last_success_at)
            if source.data is None:
                status = "unavailable" if source.error else "loading"
            elif source.error or age is None or age > source.interval * 2:
                status = "stale"
            else:
                status = "live"
            result[name] = {
                "data": source.data, "status": status, "last_success_at": source.last_success_at,
                "last_attempt_at": source.last_attempt_at, "age_seconds": round(age) if age is not None else None,
                "interval_seconds": source.interval, "error": source.error, "refreshing": source.refreshing,
            }
        return result
