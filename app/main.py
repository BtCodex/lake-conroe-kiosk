"""Local HTTP service. Upstream polling never blocks a browser request."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .cache import SourceManager, now_iso
from .config import ROOT, load_config, public_config
from .providers import alerts, camera, sjra, weather


def create_app(config: dict | None = None, providers: dict | None = None, cache_dir: Path | None = None) -> FastAPI:
    settings = config or load_config()
    adapters = providers if providers is not None else {
        "weather": weather.fetch_weather, "forecast": weather.fetch_forecast,
        "lake": sjra.fetch_lake, "alerts": alerts.fetch_alerts, "camera": camera.fetch_camera,
    }
    directory = cache_dir or Path(os.environ.get("LAKE_CONROE_CACHE_DIR", settings["server"]["cache_dir"]))
    if not directory.is_absolute():
        directory = ROOT / directory
    manager = SourceManager(settings, directory, adapters)

    @asynccontextmanager
    async def lifespan(application):
        await manager.start()
        yield
        await manager.stop()

    application = FastAPI(title="Lake Conroe Live", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    application.state.manager = manager
    application.state.config = settings

    @application.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/", include_in_schema=False)
    async def index():
        return FileResponse(ROOT / "static/index.html", headers={"Cache-Control": "no-cache"})

    @application.get("/api/config")
    async def config_endpoint():
        return public_config(settings)

    @application.get("/api/dashboard")
    async def dashboard():
        return {"generated_at": now_iso(), "config": public_config(settings), "sources": manager.snapshot()}

    @application.get("/api/health")
    async def health():
        states = manager.snapshot()
        return {"application": "lake-conroe-live",
                "status": "ok" if all(s["status"] == "live" for s in states.values()) else "degraded",
                "server_time": now_iso(), "sources": {name: {k: v for k, v in value.items() if k != "data"} for name, value in states.items()}}

    @application.get("/api/{source}")
    async def data_source(source: str):
        if source not in manager.sources:
            raise HTTPException(404, "Unknown source")
        return JSONResponse(manager.snapshot()[source])

    application.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return application


app = create_app()
