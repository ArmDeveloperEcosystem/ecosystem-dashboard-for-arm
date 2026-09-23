"""Reproducible live scenarios; coverage checks, not a general semantic-accuracy claim."""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx
from .catalog import Catalog
from .search_service import SearchService

SCENARIOS = [
    (
        "Open-source vector databases for Arm Linux",
        ["Qdrant", "Milvus", "Chroma", "Weaviate"],
        ["FreeType", "AvxToNeon", "ThirdAI Platform"],
    ),
    (
        "Databases for storing embeddings",
        ["Qdrant", "Milvus", "Chroma"],
        ["FreeType", "ThirdAI Platform"],
    ),
    (
        "Monitoring and alerting tools",
        ["Prometheus"],
        ["Cloud Hypervisor", "Harness CI", "Ubuntu Pro"],
    ),
    ("Tools to serve language models locally", ["Ollama"], ["MyHDL", "Lime", "Docker"]),
    (
        "Reverse proxy web servers",
        ["NGINX", "Haproxy"],
        ["WRK", "Jemalloc", "MySQL", "Wordpress"],
    ),
    (
        "Web servers",
        ["Apache httpd", "Caddy", "NGINX"],
        ["WRK", "Jemalloc", "MySQL", "Wordpress"],
    ),
    ("S3-compatible object storage", ["MinIO"], ["Apache Arrow", "Benchmark"]),
    (
        "Relational SQL databases",
        ["TiDB", "MySQL", "Postgres"],
        ["BenchmarkSQL", "Sqoop", "OpenCart", "OpenVVC"],
    ),
    (
        "Container orchestration",
        ["Kubernetes", "Canonical Kubernetes"],
        ["CRI-O", "Calico", "NVIDIA Container Toolkit", "Qualys Container Security"],
    ),
    (
        "Stream events with a message broker",
        ["RabbitMQ", "Kafka"],
        [
            "Restreamer",
            "Simple Real-time Server (SRS)",
            "MediaMTX",
            "Owncast",
            "Libopus",
            "Sunshine",
            "ACL",
        ],
    ),
    ("Message brokers", ["RabbitMQ", "Redis"], ["Restreamer", "ACL"]),
    ("Message queues", ["RabbitMQ", "Redis"], ["MediaMTX", "ACL"]),
    (
        "In-memory cache",
        ["Redis"],
        ["Apache Arrow", "MySQL", "Bcache", "NGINX Plus", "Harness CI"],
    ),
    ("Prometheus", ["Prometheus"], []),
    ("Weaviate", ["Weaviate"], []),
    ("Quantum teleportation hyperdrive", [], []),
    ("Vector databases with no recorded tests", [], []),
    ("Vector databases with Apache 2.0 licenses", [], []),
    ("SQL databases supporting geospatial indexes", [], []),
    ("Vector graphics tools", [], ["Qdrant", "Milvus", "Chroma", "Vector"]),
    (
        "What vector databases are available?",
        ["Qdrant", "Milvus", "Chroma"],
        ["FreeType", "Vector"],
    ),
    (
        "I am looking for a vector database",
        ["Qdrant", "Milvus", "Chroma"],
        ["FreeType", "Vector"],
    ),
    (
        "Help me find a vector database for my app",
        ["Qdrant", "Milvus", "Chroma"],
        ["FreeType", "Vector"],
    ),
    (
        "What are some open-source vector databases for Arm Linux?",
        ["Qdrant", "Milvus", "Chroma", "Weaviate"],
        ["Zilliz cloud"],
    ),
    (
        "I need a database to store JSON documents",
        ["Apache CouchDB"],
        ["Sqoop", "OpenCart", "OpenVVC"],
    ),
    (
        "I need a queue so background workers can process jobs asynchronously",
        ["RabbitMQ"],
        ["Restreamer", "MediaMTX", "ACL"],
    ),
    (
        "load balancers",
        ["Haproxy"],
        ["WRK", "Jemalloc", "MySQL", "Wordpress", "Terraform"],
    ),
    ("Tools for compressing files", ["Gzip"], ["Sqoop", "OpenCart"]),
    (
        "relational databases",
        ["Postgres", "MySQL"],
        ["Sqoop", "OpenCart", "OpenVVC", "BenchmarkSQL"],
    ),
    (
        "SQL databases",
        ["Postgres", "MySQL"],
        ["Sqoop", "OpenCart", "OpenVVC", "BenchmarkSQL"],
    ),
    ("Only web servers", ["Apache httpd", "Caddy"], ["Qdrant", "Milvus", "Chroma"]),
    ("Open-source and commercial vector databases", [], []),
    ("vector database or message broker", [], []),
]

REFINEMENTS = [
    {
        "request": {"query": "Only web servers", "previous_query": "vector databases"},
        "expected": ["Apache httpd", "Caddy"],
        "forbidden": ["Qdrant", "Milvus", "Chroma"],
    },
    {
        "request": {
            "query": "only open-source ones",
            "previous_query": "vector databases",
        },
        "expected": ["Qdrant", "Milvus", "Chroma", "Weaviate"],
        "forbidden": ["Zilliz cloud"],
        "constraints": {"license": "opensource"},
    },
    {
        "request": {
            "query": "Only those with recorded Arm64 tests",
            "previous_query": "vector databases",
        },
        "expected": ["Qdrant", "Milvus", "Chroma"],
        "forbidden": ["Zilliz cloud"],
        "constraints": {"tested_only": True},
    },
    {
        "request": {
            "query": "open-source vector databases",
            "filters": {"license": "commercial"},
            "filters_override": True,
        },
        "expected": ["Zilliz cloud"],
        "forbidden": ["Qdrant", "Milvus", "Chroma"],
        "constraints": {"license": "commercial"},
    },
]


def check_response(response, catalog, expected, forbidden, constraints=None):
    """Check identity, expected relevance, exclusions and every returned filter value."""
    returned = response["results"]
    names = {record["title"] for record in returned}
    ids = [record["id"] for record in returned]
    checks = {
        "all_ids_in_catalog": all(identity in catalog.by_id for identity in ids),
        "unique_records": len(ids) == len(set(ids)),
        "total_matches_payload": response["total"] == len(returned),
        "record_fields_match_catalog": all(
            record.get(key) == catalog.by_id.get(record["id"], {}).get(key)
            for record in returned
            for key in ("title", "category", "license", "has_recorded_tests")
        ),
        "expected_present": set(expected) <= names,
        "forbidden_absent": not set(forbidden) & names,
    }
    if not expected and not forbidden:
        checks["empty_for_unverifiable_or_absent_request"] = not names
        checks["explanation_provided"] = bool(response.get("notices"))
    filters = response.get("constraints") or {}
    for key, value in (constraints or {}).items():
        checks["constraint_" + key] = filters.get(key) == value
    checks["license_filter_respected"] = all(
        filters.get("license", "all") == "all"
        or record["license"] == filters["license"]
        for record in returned
    )
    checks["recorded_test_filter_respected"] = all(
        not filters.get("tested_only")
        or catalog.by_id.get(record["id"], {}).get("has_recorded_tests")
        for record in returned
    )
    checks["category_filter_respected"] = all(
        not filters.get("category")
        or filters["category"].lower()
        in {
            str(catalog.by_id.get(record["id"], {}).get(key, "")).lower()
            for key in ("category", "parent_category")
        }
        for record in returned
    )
    return checks


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="poc/evaluation/live-search-revised.json")
    p.add_argument(
        "--base-url", help="Run through the HTTP API, e.g. http://127.0.0.1:8765"
    )
    args = p.parse_args()
    c = Catalog(Path(".poc/public/poc-catalog.json"))
    s = SearchService(c) if not args.base_url else None
    results = []
    scenarios = [
        {"request": {"query": query}, "expected": expected, "forbidden": forbidden}
        for query, expected, forbidden in SCENARIOS
    ] + REFINEMENTS
    for scenario in scenarios:
        request = scenario["request"]
        query = request["query"]
        expected, forbidden = scenario["expected"], scenario["forbidden"]
        start = time.monotonic()
        if args.base_url:
            response = httpx.post(
                args.base_url.rstrip("/") + "/api/search", json=request, timeout=30
            )
            response.raise_for_status()
            r = response.json()
        else:
            r = s.search(**request)
        checks = check_response(r, c, expected, forbidden, scenario.get("constraints"))
        item = {
            "query": query,
            "request": request,
            "expected_examples": expected,
            "forbidden_examples": forbidden,
            "checks": checks,
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "response": r,
        }
        results.append(item)
        failures = [name for name, passed in checks.items() if not passed]
        print(
            query,
            "PASS" if not failures else "FAIL: " + ", ".join(failures),
            [p["title"] for p in r["results"][:5]],
            flush=True,
        )
    out = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "catalog_count": len(c.packages),
        "source_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                Path("poc/search_service.py"),
                Path("poc/intent.py"),
                Path("poc/relevance.py"),
                Path("poc/kb_client.py"),
            ]
            if path.exists()
        },
        "execution": "http_api" if args.base_url else "in_process",
        "evaluation": "Named scenario checks, not exhaustive coverage or a statistically representative relevance score. Returned order is backend rank; UI retains catalog alphabetical order.",
        "passed_scenarios": sum(all(x["checks"].values()) for x in results),
        "total_scenarios": len(results),
        "results": results,
    }
    Path(args.output).write_text(json.dumps(out, indent=2))
    if out["passed_scenarios"] != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
