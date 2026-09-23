"""Loopback demo host for natural-language search of the dashboard catalog."""

from __future__ import annotations
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from .catalog import Catalog
from .search_service import SearchService

ROOT = Path(__file__).resolve().parents[1]


class Filters(BaseModel):
    license: Literal["all", "opensource", "commercial"] = "all"
    category: str | None = Field(default=None, max_length=100)
    tested_only: bool = False


class SearchRequest(BaseModel):
    query: str = Field(max_length=500)
    filters: Filters = Field(default_factory=Filters)
    previous_query: str | None = Field(default=None, max_length=500)
    filters_override: bool = False


def create_app(catalog_path=None, service=None):
    catalog_path = Path(catalog_path or ROOT / ".poc/public/poc-catalog.json")
    catalog = service.catalog if service else Catalog(catalog_path)
    search = service or SearchService(catalog)
    app = FastAPI(
        title="Arm Dashboard Conversational Search PoC",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"]
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        from fastapi.responses import JSONResponse

        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"detail": "Cross-origin requests are not allowed."},
                    status_code=403,
                )
            try:
                content_length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse(
                    {"detail": "Invalid Content-Length"}, status_code=400
                )
            if content_length < 0:
                return JSONResponse(
                    {"detail": "Invalid Content-Length"}, status_code=400
                )
            if content_length > 8192:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "catalog_count": len(catalog.packages),
            "kb_configured": bool(search.endpoint),
            "hosting": "local_poc",
        }

    @app.post("/api/search")
    def search_packages(body: SearchRequest):
        return search.search(
            body.query,
            body.filters.model_dump(),
            body.previous_query,
            body.filters_override,
        )

    @app.get("/")
    def home():
        return RedirectResponse("/linux/")

    app.mount(
        "/", StaticFiles(directory=ROOT / ".poc/public", html=True), name="dashboard"
    )
    return app
