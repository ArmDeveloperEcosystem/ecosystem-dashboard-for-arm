"""Synthetic scoped KB over loopback HTTP, for integration/browser checks only.

This provider returns canned identities. It does not evaluate semantic retrieval
quality and never contacts the public KB. Start a fixture and dashboard together:

    python -m poc.evaluation.fixture_kb --port 8877 --app-port 8876

Use the built site's catalog (default .poc/public/poc-catalog.json). Ordinary
demo queries below have fixed results; unknown queries return no matches. Enter
``fixture:wrong_doc_type``, ``fixture:provider_error``, ``fixture:timeout`` or
``fixture:empty`` in the dashboard to exercise explicit failure/empty scenarios.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / ".poc/public/poc-catalog.json"
MILVUS = "linux/opensource_packages/milvus.md"
QDRANT = "linux/opensource_packages/qdrant.md"
WEAVIATE_COMMERCIAL = "linux/commercial_packages/weaviate.md"
WEAVIATE_OPEN_SOURCE = "linux/opensource_packages/weaviate.md"
RANKED_IDS = (MILVUS, WEAVIATE_COMMERCIAL, QDRANT, WEAVIATE_OPEN_SOURCE, MILVUS)

# Explicit fixtures, not synonyms or relevance rules used by the application.
DEMO_QUERIES = {
    "fixture ranked vector results": RANKED_IDS,
    "vector databases": RANKED_IDS,
    "vector databases for arm linux": RANKED_IDS,
    "find vector databases for arm linux": RANKED_IDS,
    "open-source vector databases for arm linux": RANKED_IDS,
    "weaviate": (WEAVIATE_COMMERCIAL, WEAVIATE_OPEN_SOURCE),
    "redis": ("linux/opensource_packages/redis.md",),
    "reverse proxy web servers": (
        "linux/opensource_packages/haproxy.md",
        "linux/opensource_packages/nginx.md",
    ),
    "tools to serve language models locally": ("linux/opensource_packages/ollama.md",),
    "monitoring and alerting tools": ("linux/opensource_packages/prometheus.md",),
    "visualize metrics": ("linux/opensource_packages/grafana.md",),
    "voltus": ("linux/commercial_packages/voltus.md",),
    "cadence voltus ic power integrity solution": (
        "linux/commercial_packages/voltus.md",
    ),
}
SCENARIOS = (
    "happy",
    "empty",
    "missing_metadata",
    "wrong_doc_type",
    "wrong_platform",
    "wrong_edition",
    "provider_error",
    "malformed_json",
    "timeout",
)


@dataclass
class FixtureReply:
    payload: object = field(default_factory=lambda: {"results": []})
    status: int = 200
    delay: float = 0
    raw_body: bytes | None = None


class FixtureKB(AbstractContextManager):
    """Real HTTP provider with observable requests and replaceable test replies."""

    def __init__(self, catalog_path=DEFAULT_CATALOG, *, port=0, scenario="happy"):
        rows = json.loads(Path(catalog_path).read_text())["packages"]
        self.by_id = {row["id"]: row for row in rows}
        self.scenario = scenario
        self.requests = []
        self._lock = threading.Lock()
        self.reply = self.default_reply
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path != "/search":
                    self.send_error(404)
                    return
                params = parse_qs(parsed.query, keep_blank_values=True)
                with fixture._lock:
                    fixture.requests.append(params)
                reply = fixture.reply(params)
                if reply.delay:
                    time.sleep(reply.delay)
                body = reply.raw_body
                if body is None:
                    body = json.dumps(reply.payload).encode("utf-8")
                try:
                    self.send_response(reply.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("X-Synthetic-KB-Fixture", "true")
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    # Expected when the caller abandons a deliberate timeout.
                    pass

            def log_message(self, *_args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.02),
            name="synthetic-kb-fixture",
            daemon=True,
        )

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self._server.server_port}/search"

    def hit(self, identity):
        row = self.by_id[identity]
        return {
            "url": "https://developer.arm.com/ecosystem-dashboard/linux/?"
            + urlencode({"package": row["url_id"]}),
            "title": "Synthetic fixture: " + row["title"],
            "snippet": "SYNTHETIC FIXTURE, NOT LIVE RETRIEVAL. " + row["description"],
            "doc_type": "Ecosystem Dashboard",
            "platform": "linux",
            "edition": "open-source"
            if row["license"] == "opensource"
            else "commercial",
        }

    def default_reply(self, params):
        # Validate the outbound contract, so an unscoped client cannot appear to
        # pass an integration test simply because this fixture returns good data.
        if (
            set(params) - {"q", "k", "doc_type", "platform", "edition"}
            or any(len(value) != 1 for value in params.values())
            or not params.get("q")
            or params.get("k") != ["50"]
            or params.get("doc_type") != ["Ecosystem Dashboard"]
            or params.get("platform") != ["linux"]
            or params.get("edition", ["open-source"])[0]
            not in ("open-source", "commercial")
        ):
            return FixtureReply(
                {"error": "Invalid synthetic fixture scope"}, status=400
            )
        query = params["q"][0]
        scenario = self.scenario
        if query.startswith("fixture:"):
            scenario = query.removeprefix("fixture:")
        if scenario not in SCENARIOS:
            return FixtureReply(
                {"error": "Unknown synthetic fixture scenario"}, status=400
            )
        if scenario == "provider_error":
            return FixtureReply({"error": "Synthetic provider failure"}, status=503)
        if scenario == "malformed_json":
            return FixtureReply(raw_body=b"{synthetic invalid JSON")
        if scenario == "timeout":
            return FixtureReply(delay=2)
        if scenario == "empty":
            return FixtureReply()
        ids = DEMO_QUERIES.get(query.strip().lower(), ())
        if scenario != "happy":
            ids = (
                WEAVIATE_COMMERCIAL
                if params.get("edition") == ["commercial"]
                else QDRANT,
            )
        hits = [self.hit(identity) for identity in ids]
        if "edition" in params:
            hits = [hit for hit in hits if hit["edition"] == params["edition"][0]]
        if hits:
            if scenario == "missing_metadata":
                hits[0].pop("edition")
            elif scenario == "wrong_doc_type":
                hits[0]["doc_type"] = "Learning Paths"
            elif scenario == "wrong_platform":
                hits[0]["platform"] = "windows"
            elif scenario == "wrong_edition":
                hits[0]["edition"] = (
                    "commercial"
                    if hits[0]["edition"] == "open-source"
                    else "open-source"
                )
        return FixtureReply({"results": hits, "query": query, "count": len(hits)})

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_args):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8877, help="Loopback fixture port")
    parser.add_argument(
        "--app-port", type=int, help="Also serve the dashboard on loopback"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--site-dir", type=Path, default=ROOT / ".poc/public")
    parser.add_argument("--scenario", choices=SCENARIOS, default="happy")
    args = parser.parse_args()
    with FixtureKB(args.catalog, port=args.port, scenario=args.scenario) as fixture:
        print(
            f"SYNTHETIC FIXTURE ONLY; not live KB quality evidence: {fixture.endpoint}",
            flush=True,
        )
        if args.app_port is None:
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
            return
        import uvicorn

        from poc.runtime import RuntimeConfig
        from poc.server import create_app

        config = RuntimeConfig(
            site_dir=args.site_dir,
            kb_url=fixture.endpoint,
            kb_scope_confirmed=True,
            kb_deadline=0.75,
        )
        print(
            f"Synthetic dashboard: http://127.0.0.1:{args.app_port}/linux/", flush=True
        )
        uvicorn.run(
            create_app(catalog_path=args.catalog, config=config),
            host="127.0.0.1",
            port=args.app_port,
            access_log=False,
        )


if __name__ == "__main__":
    main()
