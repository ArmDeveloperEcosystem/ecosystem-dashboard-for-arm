"""Loopback demo host: public catalog search plus a separate internal report view."""

from __future__ import annotations
import json
import os
import threading
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
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


def create_app(catalog_path=None, service=None, output_dir=None):
    catalog_path = Path(catalog_path or ROOT / ".poc/public/poc-catalog.json")
    output_dir = Path(
        output_dir
        or os.getenv("POC_DISCOVERY_OUTPUT", str(ROOT / ".poc/discovery-final"))
    )
    catalog = service.catalog if service else Catalog(catalog_path)
    search = service or SearchService(catalog)
    app = FastAPI(
        title="Arm Dashboard Local PoCs",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"]
    )
    run_lock = threading.Lock()
    run_state = {"running": False, "last_error": None}

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
        if request.url.path.startswith(("/api/", "/internal/")):
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

    @app.get("/internal/opportunities")
    def opportunities():
        return FileResponse(ROOT / "poc/web/opportunities.html")

    @app.get("/api/discovery/latest")
    def latest():
        path = output_dir / "latest.json"
        data = json.loads(path.read_text()) if path.exists() else None
        return {"run_state": run_state.copy(), "report": data}

    @app.post("/api/discovery/run")
    def run_discovery(request: Request):
        if request.headers.get("X-PoC-Request") != "discovery-run":
            raise HTTPException(403, "Use the internal run control.")
        if not run_lock.acquire(blocking=False):
            raise HTTPException(409, "A discovery run is already active.")
        run_state.update(running=True, last_error=None)

        def run():
            try:
                from .discovery import run_pipeline

                run_pipeline(
                    ROOT / "poc/discovery/config.example.yaml", output_dir, catalog_path
                )
            except Exception:
                import logging

                logging.exception("Discovery run failed")
                run_state["last_error"] = (
                    "The run could not complete. Check the local server log; prior evidence remains available."
                )
            finally:
                run_state["running"] = False
                run_lock.release()

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    @app.get("/api/discovery/download/{kind}")
    def download(kind: Literal["docx", "json", "csv"]):
        latest = output_dir / "latest.json"
        if not latest.exists():
            raise HTTPException(404, "Run discovery first.")
        report = json.loads(latest.read_text())
        stored = (report.get("report_paths") or {}).get(kind)
        if not stored:
            raise HTTPException(404, "Report format unavailable.")
        path = Path(stored).resolve()
        if not path.is_relative_to(output_dir.resolve()) or not path.is_file():
            raise HTTPException(404, "Report not found.")
        return FileResponse(path, filename=path.name)

    @app.get("/")
    def home():
        return RedirectResponse("/linux/")

    app.mount(
        "/", StaticFiles(directory=ROOT / ".poc/public", html=True), name="dashboard"
    )
    return app
