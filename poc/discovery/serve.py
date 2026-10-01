"""Loopback-only review UI. Run with python -m poc.discovery.serve.

This is a local demo, not an authenticated staging service. The public Hugo
dashboard and its deployments do not import or expose these routes.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

from .pipeline import run_pipeline


class Runner:
    def __init__(self, config, output, catalog, pipeline=run_pipeline):
        self.config, self.output, self.catalog = config, Path(output).resolve(), catalog
        self.pipeline = pipeline
        self.lock = threading.Lock()
        self.running = False
        self.error = None
        self.token = secrets.token_urlsafe(32)

    def summary(self):
        try:
            return json.loads((self.output / "latest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def start(self):
        with self.lock:
            if self.running:
                return False
            self.running, self.error = True, None
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self):
        try:
            self.pipeline(self.config, self.output, self.catalog)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {str(exc)[:400]}"
        finally:
            with self.lock:
                self.running = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Keep source query strings and data out of routine access logs.
        pass

    def send(self, code, body, content_type="application/json", filename=None):
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        if filename:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        port = self.server.server_port
        return self.headers.get("Host") in {
            f"127.0.0.1:{port}",
            f"localhost:{port}",
        } and self.headers.get("Sec-Fetch-Site") not in {"cross-site"}

    def do_GET(self):
        if not self.allowed():
            return self.send(403, '{"error":"Local requests only"}')
        path = urlsplit(self.path).path
        runner = self.server.runner
        if path == "/api/state":
            return self.send(
                200,
                json.dumps(
                    {
                        "running": runner.running,
                        "error": runner.error,
                        "csrf_token": runner.token,
                        "summary": runner.summary(),
                    }
                ),
            )
        if path == "/healthz":
            return self.send(200, '{"status":"ready","scope":"local internal demo"}')
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if path in assets:
            filename, mime = assets[path]
            return self.send(
                200, (Path(__file__).parent / "web" / filename).read_bytes(), mime
            )
        downloads = {
            "/download/docx": (
                "docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            "/download/csv": ("csv", "text/csv; charset=utf-8"),
            "/download/json": ("json", "application/json"),
        }
        if path in downloads:
            ext, mime = downloads[path]
            summary = runner.summary() or {}
            target = summary.get("report_paths", {}).get(ext)
            if target:
                target = Path(target).resolve()
                if target.is_relative_to(runner.output) and target.is_file():
                    return self.send(
                        200, target.read_bytes(), mime, f"arm64-opportunities.{ext}"
                    )
        return self.send(404, '{"error":"Not found"}')

    def do_POST(self):
        runner = self.server.runner
        expected_origin = "http://" + self.headers.get("Host", "")
        if (
            not self.allowed()
            or self.headers.get("Origin") != expected_origin
            or not secrets.compare_digest(
                self.headers.get("X-CSRF-Token", ""), runner.token
            )
        ):
            return self.send(
                403,
                '{"error":"Same-origin local requests with the session token only"}',
            )
        if self.path != "/api/run":
            return self.send(404, '{"error":"Not found"}')
        if (
            self.headers.get("Transfer-Encoding")
            or self.headers.get("Content-Length", "0") != "0"
        ):
            return self.send(
                400,
                '{"error":"Run takes no request body; edit the local configuration file"}',
            )
        if not runner.start():
            return self.send(409, '{"error":"A run is already active"}')
        return self.send(202, '{"status":"started"}')


def create_server(config, output, catalog, port=8766, *, runner=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.runner = runner or Runner(config, output, catalog)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="poc/discovery/config.example.yaml")
    parser.add_argument("--output-dir", default=".poc/discovery")
    parser.add_argument("--catalog", default="content/linux")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = create_server(args.config, args.output_dir, args.catalog, args.port)
    print(
        f"Internal opportunity review: http://127.0.0.1:{server.server_port}/",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
