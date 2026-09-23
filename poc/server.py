"""Same-origin dashboard search service; loopback remains the default boundary."""

from __future__ import annotations
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Literal
from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from .catalog import Catalog
from .http_guard import SearchBoundary, new_metrics
from .kb_client import KBClient
from .runtime import RuntimeConfig
from .search_service import SearchService

ROOT = Path(__file__).resolve().parents[1]


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    license: Literal["all", "opensource", "commercial"] = "all"
    category: str | None = Field(default=None, max_length=100)
    tested_only: bool = False


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(max_length=500)
    filters: Filters = Field(default_factory=Filters)
    previous_query: str | None = Field(default=None, max_length=500)
    filters_override: bool = False


def create_app(catalog_path=None, service=None, config: RuntimeConfig | None = None):
    config = config or RuntimeConfig.from_env()
    catalog_path = Path(catalog_path or config.site_dir / "poc-catalog.json")
    catalog = service.catalog if service else Catalog(catalog_path)
    if not catalog.packages:
        raise ValueError("Refusing to serve search with an empty dashboard catalog")
    kb_client = None
    if service is None:
        kb_client = KBClient(
            deadline=config.kb_deadline,
            max_inflight=config.kb_max_inflight,
            trust_env=False,
        )
        headers = {"User-Agent": "Arm-Ecosystem-Search/1.0"}
        if config.kb_token:
            headers["Authorization"] = "Bearer " + config.kb_token
        service = SearchService(
            catalog,
            transport=lambda query: kb_client.fetch(config.kb_url, query, headers),
        )
        service.endpoint = config.kb_url
    search = service
    metrics = new_metrics()

    @asynccontextmanager
    async def lifespan(app):
        app.state.ready = True
        try:
            yield
        finally:
            app.state.ready = False
            if kb_client:
                # Requests already admitted retain their bounded slots; supervisor
                # graceful-shutdown timeout is the final process-lifetime bound.
                kb_client.close(wait=False)

    app = FastAPI(
        title="Arm Dashboard Conversational Search",
        docs_url="/api/docs" if config.docs_enabled else None,
        openapi_url="/api/openapi.json" if config.docs_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.ready = False
    app.state.metrics = metrics
    app.state.kb_client = kb_client
    app.add_middleware(SearchBoundary, config=config, metrics=metrics)
    # Added last so an untrusted Host is rejected before origin/rate processing.
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=config.allowed_hosts, www_redirect=False
    )

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "catalog_count": len(catalog.packages),
            "kb_configured": bool(search.endpoint),
            "hosting": "same_origin_service" if config.public_origin else "local_poc",
        }

    @app.get("/api/ready")
    def ready():
        # KB availability is deliberately not a readiness condition: catalog
        # fallback still serves requests during a provider outage.
        return JSONResponse(
            {
                "status": "ready" if app.state.ready else "not_ready",
                "catalog_count": len(catalog.packages),
            },
            status_code=200 if app.state.ready else 503,
        )

    @app.post("/api/search")
    async def search_packages(body: SearchRequest):
        try:
            result = await run_in_threadpool(
                search.search,
                body.query,
                body.filters.model_dump(),
                body.previous_query,
                body.filters_override,
            )
            # Serialize inside the boundary: unexpected provider strings (for
            # example an unpaired Unicode surrogate in an evidence URL) must not
            # escape as an uncaught framework error after this handler returns.
            response = JSONResponse(result)
        except Exception as exc:
            metrics["search_internal_errors"] += 1
            # Exception messages/tracebacks may contain provider tokens or text.
            logging.getLogger("arm_search.service").error(
                "search_failed exception_type=%s", type(exc).__name__
            )
            return JSONResponse(
                {"detail": "Search is temporarily unavailable."}, status_code=503
            )
        if result.get("mode") == "catalog_fallback":
            metrics["catalog_fallback_responses"] += 1
            logging.getLogger("arm_search.service").info("search_used_catalog_fallback")
        return response

    @app.get("/")
    def home():
        if not config.serve_static:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return RedirectResponse("/linux/")

    if config.serve_static:
        app.mount(
            "/", StaticFiles(directory=config.site_dir, html=True), name="dashboard"
        )
    return app
