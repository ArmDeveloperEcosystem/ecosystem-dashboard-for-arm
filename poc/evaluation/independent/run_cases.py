"""Independent HTTP cases; writes evidence without modifying tracked sources."""

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

CASE_DIR = Path(__file__).resolve().parent
ROOT = next(
    parent for parent in CASE_DIR.parents if (parent / "poc/catalog.py").is_file()
)
sys.path.insert(0, str(ROOT))
from poc.catalog import Catalog


def assess(case, payload, catalog):
    result = payload.get("results", [])
    notices = payload.get("notices", [])
    exp = case["expect"]
    names = {p["title"] for p in result}
    ids = {p["id"] for p in result}
    errors = []
    for p in result:
        original = catalog.by_id.get(p["id"])
        if not original:
            errors.append("unknown catalog identity: " + p["id"])
            continue
        if not (ROOT / "content" / p["id"]).is_file():
            errors.append("missing source record: " + p["id"])
        for field in ("title", "category", "license", "has_recorded_tests"):
            if p.get(field) != original.get(field):
                errors.append("catalog field mismatch: " + p["id"] + "/" + field)
    decline = exp.get("allow_explicit_decline") and not result and bool(notices)
    if not decline:
        for name in exp.get("required_titles", []):
            if name not in names:
                errors.append("missing expected title: " + name)
        for package_id in exp.get("required_ids", []):
            if package_id not in ids:
                errors.append("missing expected ID: " + package_id)
        for group in exp.get("any_group", []):
            if not names.intersection(group):
                errors.append("missing expected alternative: " + ", ".join(group))
        for license_type in exp.get("required_licenses", []):
            if not any(p["license"] == license_type for p in result):
                errors.append("missing license class: " + license_type)
    for name in exp.get("forbidden_titles", []):
        if name in names:
            errors.append("unexpected title: " + name)
    for package_id in exp.get("forbidden_ids", []):
        if package_id in ids:
            errors.append("unexpected ID: " + package_id)
    for evidence in exp.get("forbidden_evidence", []):
        if any(
            p["id"] == evidence["id"] and p.get("evidence_url") == evidence["url"]
            for p in result
        ):
            errors.append("unsupported evidence attribution: " + evidence["id"])
    if exp.get("empty_with_notice") and (result or not notices):
        errors.append("expected empty result and honest notice")
    if exp.get("nonempty") and not result:
        errors.append("expected nonempty result")
    for field in ("license", "category"):
        if field in exp and any(p[field] != exp[field] for p in result):
            errors.append("result violates expected " + field)
    if exp.get("tested_only") and (
        not payload.get("constraints", {}).get("tested_only")
        or any(not p["has_recorded_tests"] for p in result)
    ):
        errors.append("recorded-test constraint not honored")
    if "allowed_titles" in exp and names - set(exp["allowed_titles"]):
        errors.append(
            "unrelated titles: " + ", ".join(sorted(names - set(exp["allowed_titles"])))
        )
    for field in ("status", "mode", "interpreted_query"):
        if field in exp and payload.get(field) != exp[field]:
            errors.append("unexpected " + field + ": " + str(payload.get(field)))
    return {
        "scenario_check_passed": not errors,
        "errors": errors,
        "accepted_explicit_decline": bool(decline),
        "title_count": len(names),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--output", default="regression-http-rerun.json")
    parser.add_argument("--cases", default="regression_cases.json")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    catalog = Catalog(ROOT / ".poc/public/poc-catalog.json")
    cases = json.loads((CASE_DIR / args.cases).read_text())["cases"]

    def one(case):
        start = time.monotonic()
        entry = {"id": case["id"], "family": case["family"], "request": case["request"]}
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    args.base_url + "/api/search", json=case["request"]
                )
                entry["http_status"] = response.status_code
                response.raise_for_status()
                entry["response"] = response.json()
                entry["assessment"] = assess(case, entry["response"], catalog)
        except Exception as exc:
            entry["exception"] = repr(exc)
            entry["assessment"] = {
                "scenario_check_passed": False,
                "errors": [repr(exc)],
            }
        entry["seconds"] = round(time.monotonic() - start, 3)
        return entry

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(one, cases))
    output = {
        "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_sha256": {
            str(path): hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in map(
                Path,
                [
                    "poc/search_service.py",
                    "poc/catalog.py",
                    "poc/server.py",
                    "poc/intent.py",
                    "poc/relevance.py",
                    "poc/kb_client.py",
                ],
            )
        },
        "catalog_count": len(catalog.packages),
        "purpose": "Finite independent scenario checks; the summary is not an accuracy rate.",
        "cases": results,
    }
    destination = CASE_DIR / args.output
    destination.write_text(json.dumps(output, indent=2) + "\n")
    print("Evidence:", destination)
    for entry in results:
        result = entry.get("response", {})
        assessment = entry["assessment"]
        print(
            entry["id"],
            "PASS" if assessment["scenario_check_passed"] else "FLAG",
            entry["request"]["query"],
        )
        print("  ", ", ".join(p["title"] for p in result.get("results", [])))
        if assessment.get("errors"):
            print("  ", "; ".join(assessment["errors"]))
        if result.get("notices"):
            print("  Notices:", " | ".join(result["notices"]))
    print(
        "Scenario checks passing:",
        sum(r["assessment"]["scenario_check_passed"] for r in results),
        "of",
        len(results),
    )


if __name__ == "__main__":
    main()
