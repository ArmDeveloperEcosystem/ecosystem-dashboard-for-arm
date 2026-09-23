"""Run the held-out HTTP cases and record source hashes before and after the run."""

import argparse
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

CASE_DIR = Path(__file__).resolve().parent
ROOT = next(parent for parent in CASE_DIR.parents if (parent / "poc/catalog.py").is_file())
sys.path.insert(0, str(ROOT))
from poc.catalog import Catalog
from poc.evaluation.run_cases import assess as assess_case


def assess(case, payload, catalog):
    assessment = assess_case(case, payload, catalog)
    results = payload.get("results", [])
    if payload.get("total") != len(results):
        assessment["errors"].append("total does not equal returned result length")
    ids = [record["id"] for record in results]
    if len(set(ids)) != len(ids):
        assessment["errors"].append("duplicate result IDs")
    category = case["expect"].get("category_or_parent")
    if category and any(
        category not in (
            catalog.by_id[record["id"]]["category"],
            catalog.by_id[record["id"]]["parent_category"],
        )
        for record in results
    ):
        assessment["errors"].append("category or parent constraint violated")
    assessment["scenario_check_passed"] = not assessment["errors"]
    return assessment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".poc/evaluation/heldout-http.json"
    )
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()

    source = args.source_root.resolve()
    catalog = Catalog(source / ".poc/public/poc-catalog.json")
    case_path = CASE_DIR / "heldout_cases.json"
    cases = json.loads(case_path.read_text())["cases"]
    paths = list((source / "poc").glob("*.py")) + [source / ".poc/public/poc-catalog.json"]

    def hashes():
        return {
            str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    before = hashes()
    rows = []
    with httpx.Client(timeout=35) as client:
        for case in cases:
            started = time.monotonic()
            entry = {
                "id": case["id"],
                "family": case["family"],
                "request": case["request"],
                "expect": case["expect"],
            }
            try:
                response = client.post(
                    args.base_url.rstrip("/") + "/api/search", json=case["request"]
                )
                entry["http_status"] = response.status_code
                response.raise_for_status()
                entry["response"] = response.json()
                entry["assessment"] = assess(case, entry["response"], catalog)
            except Exception as exc:
                entry["assessment"] = {
                    "scenario_check_passed": False,
                    "errors": [repr(exc)],
                }
            entry["seconds"] = round(time.monotonic() - started, 3)
            rows.append(entry)
            print(
                case["id"],
                "PASS" if entry["assessment"]["scenario_check_passed"] else "FLAG",
                entry["seconds"],
                [record["title"] for record in entry.get("response", {}).get("results", [])],
                entry["assessment"].get("errors"),
                flush=True,
            )
            args.output.write_text(
                json.dumps({"started_source_sha256": before, "cases": rows}, indent=2) + "\n"
            )
    after = hashes()
    output = {
        "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "started_source_sha256": before,
        "finished_source_sha256": after,
        "sources_frozen": before == after,
        "catalog_count": len(catalog.packages),
        "case_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
        "cases": rows,
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(
        "Passed", sum(row["assessment"]["scenario_check_passed"] for row in rows),
        "/", len(rows), "source frozen", before == after,
    )
    if before != after or not all(row["assessment"]["scenario_check_passed"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
