"""Controlled local capacity/rate probes on ports 8772–8774; not a throughput claim."""

import argparse
import asyncio
import collections
import datetime
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / "poc/catalog.py").is_file()
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".poc/evaluation/operations.json"
    )
    parser.add_argument("--log-dir", type=Path, default=ROOT / ".poc/evaluation")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)

    state = {"requests": 0, "active": 0, "max_active": 0}
    lock = threading.Lock()

    class KB(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            with lock:
                state["requests"] += 1
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            try:
                time.sleep(0.8)
                data = b'{"results":[]}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with lock:
                    state["active"] -= 1

    kb = ThreadingHTTPServer(("127.0.0.1", 8772), KB)
    threading.Thread(target=kb.serve_forever, daemon=True).start()
    processes = []
    logs = []
    output = {
        "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Local controlled HTTP experiment only; not production throughput certification.",
        "phases": [],
    }

    def launch(port, **changes):
        env = os.environ.copy()
        env.pop("ARM_KB_API_TOKEN", None)
        env.update({
            "ARM_SEARCH_PUBLIC_ORIGIN": "https://dashboard.example",
            "ARM_SEARCH_SERVE_STATIC": "false",
            "ARM_KB_SEARCH_URL": "http://127.0.0.1:8772",
            "ARM_SEARCH_MAX_INFLIGHT": "2",
            "ARM_SEARCH_KB_MAX_INFLIGHT": "2",
            "ARM_SEARCH_KB_DEADLINE": "0.15",
            "ARM_SEARCH_REQUESTS_PER_MINUTE": "1000",
            "PYTHONUNBUFFERED": "1",
        })
        env.update(changes)
        path = args.log_dir / f"operations-{port}.log"
        log = path.open("w")
        logs.append((log, path))
        process = subprocess.Popen(
            [sys.executable, "-m", "poc.serve", "--port", str(port)],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        processes.append(process)
        for _ in range(100):
            try:
                response = httpx.get(
                    f"http://127.0.0.1:{port}/api/ready",
                    headers={"Host": "dashboard.example"}, timeout=0.2,
                )
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise RuntimeError("Local profile failed startup")

    async def burst():
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8773",
            headers={"Host": "dashboard.example", "Origin": "https://dashboard.example"},
            limits=httpx.Limits(max_connections=50), timeout=10,
        ) as client:
            async def one():
                started = time.monotonic()
                response = await client.post("/api/search", json={"query": "vector databases"})
                data = response.json()
                return {
                    "status": response.status_code,
                    "seconds": round(time.monotonic() - started, 4),
                    "mode": data.get("mode"),
                    "has_notice": bool(data.get("notices")),
                    "retry_after": response.headers.get("retry-after"),
                }

            rows = await asyncio.gather(*(one() for _ in range(30)))
            output["phases"].append({
                "name": "30_simultaneous_requests_max_inflight_2",
                "results": rows,
                "status_counts": dict(collections.Counter(row["status"] for row in rows)),
                "latency_p50": statistics.median(row["seconds"] for row in rows),
                "latency_p95": sorted(row["seconds"] for row in rows)[28],
                "max_provider_active": state["max_active"],
            })
            await asyncio.sleep(1)
            response = await client.post("/api/search", json={"query": "Qdrant"})
            output["phases"].append({
                "name": "recovery_after_slow_provider",
                "status": response.status_code,
                "mode": response.json().get("mode"),
                "titles": [record["title"] for record in response.json().get("results", [])],
            })

    try:
        launch(8773)
        asyncio.run(burst())
        launch(8774, ARM_SEARCH_REQUESTS_PER_MINUTE="2", ARM_KB_SEARCH_URL="http://127.0.0.1:9")
        rate = []
        with httpx.Client(
            base_url="http://127.0.0.1:8774", headers={"Host": "dashboard.example"}, timeout=5,
        ) as client:
            for index in range(3):
                response = client.post(
                    "/api/search", headers={"X-Forwarded-For": f"198.51.100.{index + 1}"},
                    json={"query": "Qdrant"},
                )
                rate.append({
                    "status": response.status_code,
                    "retry_after": response.headers.get("retry-after"),
                })
            health = client.get("/api/ready")
            docs = client.get("/api/docs")
            output["phases"].append({
                "name": "rate_limit_ignores_untrusted_forwarded_ip",
                "requests": rate,
                "readiness_after_limit": health.status_code,
                "production_docs_status": docs.status_code,
            })
        output["provider_observations"] = dict(state)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log, _ in logs:
            log.close()
        kb.shutdown()
        kb.server_close()
        output["log_privacy"] = {
            path.name: {
                "raw_query_present": "Qdrant" in path.read_text() or "vector database" in path.read_text(),
                "sample": path.read_text()[:1200],
            }
            for _, path in logs
        }
        args.output.write_text(json.dumps(output, indent=2) + "\n")
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
