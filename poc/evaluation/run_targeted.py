"""Controlled provider fixtures over real catalog records; not live claims."""

import argparse
import datetime
import json
import socket
import sys
import time
from pathlib import Path

ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / "poc/catalog.py").is_file()
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--slow-body-port", type=int)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".poc/evaluation/targeted.json"
    )
    args = parser.parse_args()
    source = args.source_root.resolve()
    sys.path.insert(0, str(source))
    from poc.catalog import Catalog
    from poc.search_service import SearchService
    from poc.server import create_app
    from poc.runtime import RuntimeConfig
    from fastapi.testclient import TestClient

    catalog = Catalog(source / ".poc/public/poc-catalog.json")
    rows = []

    def run(case_id, query, title, snippet, required=(), forbidden=()):
        hit = {
            "title": title,
            "url": (
                "https://developer.arm.com/ecosystem-dashboard/linux/?package=redis"
                if title.startswith("Redis ") else "https://learn.arm.com/reviewer-controlled-fixture/"
            ),
            "snippet": snippet,
        }
        payload = SearchService(catalog, transport=lambda _: {"results": [hit]}).search(query)
        names = {record["title"] for record in payload["results"]}
        errors = [f"missing {name}" for name in required if name not in names]
        errors += [f"unexpected {name}" for name in forbidden if name in names]
        rows.append({
            "id": case_id,
            "query": query,
            "controlled_hit": hit,
            "required_titles": required,
            "forbidden_titles": forbidden,
            "response": payload,
            "errors": errors,
            "passed": not errors,
        })
        print(case_id, "PASS" if not errors else "FLAG", sorted(names), errors)

    run("trailing-negation", "encryption tools", "RabbitMQ security",
        "Encryption is not supported by RabbitMQ.", forbidden=["RabbitMQ"])
    run("contracted-negation", "encryption tools", "RabbitMQ security",
        "RabbitMQ doesn't support encryption.", forbidden=["RabbitMQ"])
    run("positive-evidence", "encryption tools", "RabbitMQ security",
        "RabbitMQ has encryption enabled.", required=["RabbitMQ"])
    run("compound-false", "multi-tenant databases", "Redis architecture",
        "Redis supports multiple engines and tenant metadata.", forbidden=["Redis"])
    run("compound-positive", "multi-tenant databases", "Redis architecture",
        "Redis is a multi-tenant in-memory database.", required=["Redis"])
    run("protocol-operational-mention", "load balancer for TCP and HTTP applications", "Install NGINX",
        "Allow HTTP traffic through the VM firewall. Run sudo ufw allow 80/tcp.",
        required=["Haproxy"], forbidden=["NGINX"])
    run("protocol-positive", "load balancer for TCP and HTTP applications", "NGINX networking",
        "NGINX provides TCP and HTTP load balancing.", required=["NGINX", "Haproxy"])
    hit = {
        "title": "Qdrant vector database",
        "url": "https://learn.arm.com/qdrant/\ud800",
        "snippet": "Qdrant is a vector database.",
    }
    service = SearchService(catalog, transport=lambda _: {"results": [hit]})
    with TestClient(
        create_app(service=service, config=RuntimeConfig(site_dir=source / ".poc/public", serve_static=False)),
        base_url="http://127.0.0.1", raise_server_exceptions=False,
    ) as client:
        response = client.post("/api/search", json={"query": "vector databases"})
        rows.append({
            "id": "malformed-provider-url-serialization",
            "http_status": response.status_code,
            "response": response.json(),
            "passed": response.status_code == 503 and response.json() == {"detail": "Search is temporarily unavailable."},
        })
    if args.slow_body_port:
        started = time.monotonic()
        with socket.create_connection(("127.0.0.1", args.slow_body_port), timeout=10) as connection:
            connection.sendall(
                b"POST /api/search HTTP/1.1\r\nHost: dashboard.example\r\n"
                b"Content-Type: application/json\r\nContent-Length: 18\r\n"
                b'Connection: close\r\n\r\n{"query":'
            )
            reply = connection.recv(4096).decode()
            status = reply.splitlines()[0]
            rows.append({
                "id": "slow-actual-http-body",
                "status_line": status,
                "seconds": round(time.monotonic() - started, 3),
                "passed": "408" in status,
            })
    output = {
        "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "Synthetic controlled KB fixtures establish parser and attribution behavior, not facts about the named projects. ActualHTTP slow body and ASGI provider serialization separate.",
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print("Passed", sum(row["passed"] for row in rows), "/", len(rows))
    if not all(row["passed"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
