"""GeoPulse v2 FastAPI application."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import admin, auth, entities, projects, prompts, reports, waves, workflow
from .migrations import SCHEMA_VERSION, current_version
from .services.measurement import Worker
from .services.scheduler import Scheduler

logger = logging.getLogger("geopulse")
logging.basicConfig(level=logging.INFO, format="%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    disabled = os.environ.get("GEOPULSE_DISABLE_WORKER") == "1"
    worker, scheduler = Worker(), Scheduler()
    if not disabled:
        worker.start()
        scheduler.start()
    app.state.worker = worker
    app.state.scheduler = scheduler
    yield
    scheduler.stop()
    worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="GeoPulse", version="2.0.0",
                  description="可复现、可对比、可审计的 GEO 客户交付系统", lifespan=lifespan)

    @app.middleware("http")
    async def observability(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'")
        logger.info(json.dumps({"request_id": request_id, "method": request.method, "path": request.url.path,
                                "status": response.status_code, "latency_ms": int((time.monotonic() - started) * 1000)},
                               ensure_ascii=False))
        return response

    for router in (auth.router, projects.router, prompts.router, entities.router, waves.router,
                   workflow.router, reports.router, admin.router):
        app.include_router(router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "2.0.0", "schema_version": current_version(),
                "expected_schema": SCHEMA_VERSION, "worker": os.environ.get("GEOPULSE_DISABLE_WORKER") != "1"}

    if config.FRONTEND.is_dir():
        app.mount("/static", StaticFiles(directory=str(config.FRONTEND)), name="static")

        @app.get("/")
        def index():
            return FileResponse(config.FRONTEND / "index.html")

    return app


app = create_app()
