"""Record representative HTTP searches; provider relevance requires human review."""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .catalog import Catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--environment-label",
        required=True,
        help="Identify the actual provider/environment, including synthetic fixtures",
    )
    parser.add_argument(
        "--catalog", type=Path, default=Path(".poc/public/poc-catalog.json")
    )
    parser.add_argument(
        "--cases", type=Path, default=Path("poc/evaluation/search_cases.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".poc/evaluation/scoped-search.json")
    )
    args = parser.parse_args()
    catalog = Catalog(args.catalog)
    cases = json.loads(args.cases.read_text())["cases"]
    records = []
    with httpx.Client(
        base_url=args.base_url.rstrip("/"), timeout=15, trust_env=False
    ) as client:
        for case in cases:
            started = time.monotonic()
            row = {
                "request": case["request"],
                "expected_examples": case["expected_examples"],
            }
            try:
                response = client.post("/api/search", json=case["request"])
                payload = response.json()
                if not isinstance(payload, dict):
                    raise TypeError("Search response must be an object")
                results = payload.get("results", [])
                if not isinstance(results, list) or not all(
                    isinstance(item, dict) for item in results
                ):
                    raise TypeError("Search results must be a list of objects")
                identities = [item["id"] for item in results]
                names = {item["title"] for item in results}
                filters = case["request"].get("filters", {})
                checks = {
                    "scoped_provider_available": response.status_code == 200
                    and payload.get("mode") == "kb_scoped",
                    "query_unchanged": payload.get("query") == case["request"]["query"],
                    "current_catalog_records": all(
                        identity in catalog.by_id for identity in identities
                    ),
                    "unique_records": len(identities) == len(set(identities)),
                    "displayed_descriptions": all(
                        item.get("reason")
                        == catalog.by_id.get(item["id"], {}).get("description")
                        for item in results
                    ),
                    "category_filter": all(
                        not filters.get("category")
                        or filters["category"].casefold()
                        in (
                            str(
                                catalog.by_id.get(item["id"], {}).get("category", "")
                            ).casefold(),
                            str(
                                catalog.by_id.get(item["id"], {}).get(
                                    "parent_category", ""
                                )
                            ).casefold(),
                        )
                        for item in results
                    ),
                    "expected_examples_present": set(case["expected_examples"])
                    <= names,
                    "current_fields": all(
                        item.get(field) == catalog.by_id.get(item["id"], {}).get(field)
                        for item in results
                        for field in (
                            "title",
                            "category",
                            "license",
                            "has_recorded_tests",
                        )
                    ),
                    "license_filter": all(
                        filters.get("license", "all") in ("all", item["license"])
                        for item in results
                    ),
                    "recorded_test_filter": all(
                        not filters.get("tested_only") or item["has_recorded_tests"]
                        for item in results
                    ),
                }
                row.update(
                    http_status=response.status_code, checks=checks, response=payload
                )
                row["passed"] = all(checks.values())
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                row.update(passed=False, error_type=type(exc).__name__)
            row["elapsed_seconds"] = round(time.monotonic() - started, 4)
            records.append(row)
            print(
                case["request"]["query"],
                "PASS" if row["passed"] else "REVIEW / UNAVAILABLE",
                flush=True,
            )
    report = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "environment": args.environment_label,
        "catalog_sha256": hashlib.sha256(args.catalog.read_bytes()).hexdigest(),
        "scope": "Draft representative examples, not an exhaustive relevance benchmark. Inspect every returned row; fixture success does not validate live retrieval. Cold/warm provider state is uncontrolled.",
        "results": records,
        "passed": all(row["passed"] for row in records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(args.output)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
