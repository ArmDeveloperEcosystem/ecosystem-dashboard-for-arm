"""Read-only local HTTP boundary probes; no public load or access tokens."""

import argparse
import datetime
import json
import time
from pathlib import Path

import httpx

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / "poc/catalog.py").is_file()
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--host")
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".poc/evaluation/boundary-http.json"
    )
    args = parser.parse_args()
    headers = {"Host": args.host} if args.host else {}
    rows = []

    def check(label, method, path, expected, **kwargs):
        started = time.monotonic()
        try:
            request_headers = dict(headers)
            request_headers.update(kwargs.pop("headers", {}))
            response = httpx.request(
                method, args.base_url.rstrip("/") + path,
                headers=request_headers, timeout=20, **kwargs,
            )
            # Save response/status metadata, never submitted bodies or credentials.
            rows.append({
                "id": label,
                "http_status": response.status_code,
                "expected_statuses": expected,
                "passed": response.status_code in expected,
                "response": response.text[:600],
                "cache_control": response.headers.get("cache-control"),
                "content_type": response.headers.get("content-type"),
                "request_id": response.headers.get("x-request-id"),
                "seconds": round(time.monotonic() - started, 3),
            })
        except Exception as exc:
            rows.append({
                "id": label, "passed": False, "exception": repr(exc),
                "seconds": round(time.monotonic() - started, 3),
            })
        print(rows[-1], flush=True)

    check("health", "GET", "/api/health", [200])
    check("readiness", "GET", "/api/ready", [200])
    check("host-rejected", "POST", "/api/search", [400],
          headers={"Host": "attacker.invalid"}, json={"query": "Qdrant"})
    check("origin-rejected", "POST", "/api/search", [403],
          headers={"Origin": "https://attacker.invalid"}, json={"query": "Qdrant"})
    check("declared-large-body", "POST", "/api/search", [413],
          content=b" " * 9000, headers={"Content-Type": "application/json"})

    def chunks():
        for _ in range(10):
            yield b" " * 1000

    check("chunked-large-body", "POST", "/api/search", [413],
          content=chunks(), headers={"Content-Type": "application/json"})
    check("malformed-json", "POST", "/api/search", [400, 422],
          content=b'{"query":', headers={"Content-Type": "application/json"})
    check("invalid-utf8", "POST", "/api/search", [400, 422],
          content=b'{"query":"\xff"}', headers={"Content-Type": "application/json"})
    check("deep-json", "POST", "/api/search", [400, 422],
          content=("[" * 1100 + "0" + "]" * 1100).encode(),
          headers={"Content-Type": "application/json"})
    check("oversized-query", "POST", "/api/search", [422], json={"query": "x" * 501})
    check("object-query", "POST", "/api/search", [422], json={"query": {"nested": "value"}})
    check("invalid-license", "POST", "/api/search", [422],
          json={"query": "database", "filters": {"license": "magic"}})
    check("array-root", "POST", "/api/search", [422], json=[{"query": "Qdrant"}])
    check("null-root", "POST", "/api/search", [422],
          content=b"null", headers={"Content-Type": "application/json"})
    check("unknown-api", "GET", "/api/does-not-exist", [404])
    check("server-file-inaccessible", "GET", "/poc/server.py", [404])
    check("dotfile-inaccessible", "GET", "/.env", [404])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_url": args.base_url,
        "cases": rows,
    }, indent=2) + "\n")
    print("Expected status observed:", sum(row["passed"] for row in rows), "/", len(rows))
    if not all(row["passed"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
