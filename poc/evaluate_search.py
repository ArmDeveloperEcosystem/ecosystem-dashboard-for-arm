"""Reproducible live scenarios; coverage checks, not a general semantic-accuracy claim."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
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
    ("Tools to serve language models locally", ["Ollama"], ["MyHDL", "Lime"]),
    ("Reverse proxy web servers", ["NGINX", "Haproxy"], ["WRK", "Jemalloc"]),
    ("Web servers", ["Apache httpd", "Caddy", "NGINX"], ["WRK", "Jemalloc"]),
    ("S3-compatible object storage", ["MinIO"], []),
    ("Relational SQL databases", ["TiDB", "MySQL"], ["BenchmarkSQL"]),
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
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="poc/evaluation/live-search-final.json")
    args = p.parse_args()
    c = Catalog(Path(".poc/public/poc-catalog.json"))
    s = SearchService(c)
    results = []
    for query, expected, forbidden in SCENARIOS:
        start = time.monotonic()
        r = s.search(query)
        names = {p["title"] for p in r["results"]}
        checks = {
            "all_ids_in_catalog": all(p["id"] in c.by_id for p in r["results"]),
            "expected_present": set(expected) <= names,
            "forbidden_absent": not set(forbidden) & names,
        }
        if not expected and not forbidden:
            checks["empty_for_unverifiable_or_absent_request"] = not names
        item = {
            "query": query,
            "expected_examples": expected,
            "forbidden_examples": forbidden,
            "checks": checks,
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "response": r,
        }
        results.append(item)
        print(query, checks, [p["title"] for p in r["results"][:5]], flush=True)
    out = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "catalog_count": len(c.packages),
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
