"""Exercise the built API image with production settings and controlled KB outage."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import quote, quote_plus
import uuid

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="arm-dashboard-search:ci")
    parser.add_argument("--docker-context")
    parser.add_argument("--output")
    args = parser.parse_args()
    docker = ["docker"]
    if args.docker_context:
        docker += ["--context", args.docker_context]

    def run(*arguments):
        return subprocess.check_output(docker + list(arguments), text=True).strip()

    name = "arm-search-smoke-" + uuid.uuid4().hex[:12]
    checks = {}
    created = False
    try:
        run(
            "run", "-d", "--name", name,
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "512m", "--cpus", "2", "--pids-limit", "128",
            "-p", "127.0.0.1::8080",
            "-e", "ARM_SEARCH_PUBLIC_ORIGIN=https://search.example.test",
            "-e", "ARM_KB_SEARCH_URL=http://127.0.0.1:9/search",
            "-e", "ARM_KB_API_TOKEN=smoke-test-not-a-real-secret",
            args.image,
        )
        created = True
        info = json.loads(run("inspect", name))[0]
        port = info["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"]
        base = "http://127.0.0.1:" + port
        with httpx.Client(
            base_url=base, headers={"Host": "search.example.test"},
            timeout=20, trust_env=False,
        ) as client:
            deadline = time.monotonic() + 45
            while True:
                try:
                    if client.get("/api/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Container did not become ready")
                time.sleep(0.25)
            checks["readiness"] = True
            checks["liveness"] = client.get("/api/health").status_code == 200
            response = client.post(
                "/api/search", json={"query": "Open-source vector databases"},
                headers={"Origin": "https://search.example.test"},
            )
            response.raise_for_status()
            payload = response.json()
            catalog = json.loads(Path(".poc/public/poc-catalog.json").read_text())
            ids = {p["id"] for p in catalog["packages"]}
            checks["real_catalog_records"] = bool(payload["results"]) and all(
                p["id"] in ids for p in payload["results"]
            )
            checks["expected_discovery"] = {"Qdrant", "Milvus", "Chroma"} <= {
                p["title"] for p in payload["results"]
            }
            checks["open_source_filter"] = all(
                p["license"] == "opensource" for p in payload["results"]
            )
            checks["labeled_provider_outage"] = payload["mode"] == "catalog_fallback"
            checks["production_evidence_path"] = all(
                p["evidence_url"].startswith("/ecosystem-dashboard/linux/?package=")
                for p in payload["results"]
            )
            checks["response_no_store"] = "no-store" in response.headers["cache-control"]
            checks["unconfigured_host_rejected"] = client.get(
                "/api/health", headers={"Host": "untrusted.example"}
            ).status_code == 400
            checks["cross_origin_rejected"] = client.post(
                "/api/search", json={"query": "Prometheus"},
                headers={"Origin": "https://untrusted.example"},
            ).status_code == 403
            checks["public_documentation_disabled"] = all(
                client.get(path).status_code == 404
                for path in ("/api/docs", "/api/openapi.json", "/")
            )
            checks["chunked_oversized_body_rejected"] = client.post(
                "/api/search", content=iter([b" " * 4096] * 3),
                headers={"Content-Type": "application/json"},
            ).status_code == 413
            checks["deep_json_rejected"] = client.post(
                "/api/search", content=b"[" * 1000 + b"]" * 1000,
                headers={"Content-Type": "application/json"},
            ).status_code == 400
        checks["nonroot"] = info["Config"]["User"] == "10001:10001"
        checks["read_only"] = info["HostConfig"]["ReadonlyRootfs"]
        checks["bounded_resources"] = (
            info["HostConfig"]["Memory"] == 512 * 1024 * 1024
            and info["HostConfig"]["PidsLimit"] == 128
        )
        catalog_digest = hashlib.sha256(
            Path(".poc/public/poc-catalog.json").read_bytes()
        ).hexdigest()
        checks["matching_catalog_snapshot"] = run(
            "exec", name, "python", "-c",
            "import hashlib; from pathlib import Path; "
            "print(hashlib.sha256(Path('/app/site/poc-catalog.json').read_bytes()).hexdigest())",
        ) == catalog_digest
        log_result = subprocess.run(
            docker + ["logs", name], check=True, text=True, capture_output=True
        )
        logs = log_result.stdout + log_result.stderr
        private_values = {"smoke-test-not-a-real-secret"}
        for query in ("Open-source vector databases", "vector database"):
            private_values.update((query, quote(query), quote_plus(query)))
        checks["private_logs"] = "search_request status=" in logs and all(
            text not in logs for text in private_values
        )
        image = json.loads(run("image", "inspect", args.image))[0]
        report = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "image_id": image["Id"], "architecture": image["Architecture"],
            "catalog_sha256": catalog_digest,
            "checks": checks, "passed": all(checks.values()),
            "scope": "Real local container, production settings, controlled KB outage; not cloud rollout or live-provider load validation.",
        }
        if args.output:
            Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        if not report["passed"]:
            raise SystemExit(1)
    finally:
        if created:
            run("rm", "-f", name)


if __name__ == "__main__":
    main()
