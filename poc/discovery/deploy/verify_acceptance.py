"""Read-only checks for a saved acceptance run, never a production approval."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ..pipeline import review_evidence

MAX_REPORT_BYTES = 25_000_000


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Observation time must include a timezone")
    return parsed.astimezone(timezone.utc)


def assess(summary, *, mode="ai", minimum_findings=1, max_age_hours=24, now=None):
    """Validate current evidence and advisory coverage without making network calls."""
    if mode not in {"ai", "metadata"}:
        raise ValueError("Mode must be ai or metadata")
    for value in (minimum_findings, max_age_hours):
        if type(value) is not int or value < 1:
            raise ValueError("Acceptance limits must be positive integers")
    errors = []
    now = now or datetime.now(timezone.utc)
    if not isinstance(summary, dict):
        return ["Report must be a JSON object"]
    if not isinstance(summary.get("run_id"), str) or not summary["run_id"].strip():
        errors.append("Report is missing its run identity")
    if summary.get("status") != "completed" or summary.get("outcome") != "completed":
        errors.append("Run did not finish with a healthy completed outcome")
    if summary.get("current_errors") != []:
        errors.append("Run has current errors or missing health information")
    try:
        generated = timestamp(summary["generated_at"])
        age = (now - generated).total_seconds()
        if age < 0 or age > max_age_hours * 3600:
            errors.append(
                "Run observation time is future-dated or exceeds the acceptance age limit"
            )
    except (KeyError, TypeError, AttributeError, ValueError):
        errors.append("Run observation time is missing or invalid")
    findings = summary.get("findings")
    if not isinstance(findings, list):
        return errors + ["Current findings must be a list"]
    if len(findings) < minimum_findings:
        errors.append(
            "Insufficient current findings; saved history or a no-work run is not acceptance evidence"
        )
    counts = summary.get("counts")
    counts = counts if isinstance(counts, dict) else {}
    actual = {"investigated": len(findings), "supported": 0, "gap": 0, "unknown": 0}
    identities, eligible, completed = set(), 0, 0
    for index, finding in enumerate(findings):
        label = f"Finding {index + 1}"
        if not isinstance(finding, dict):
            errors.append(label + " is malformed")
            continue
        identity = finding.get("candidate_id")
        if not isinstance(identity, str) or not identity or identity in identities:
            errors.append(label + " has a missing or duplicate identity")
        else:
            identities.add(identity)
        status = finding.get("status")
        if status not in ("supported", "gap", "unknown"):
            errors.append(label + " has an invalid support status")
        else:
            actual[status] += 1
        if finding.get("historical") or finding.get("checked_at") != summary.get(
            "generated_at"
        ):
            errors.append(label + " is not a current observation from this run")
        if not isinstance(finding.get("scope"), str) or not finding["scope"].strip():
            errors.append(label + " is missing its checked scope")
        evidence = finding.get("evidence")
        valid_evidence = isinstance(evidence, list) and all(
            isinstance(item, dict)
            and all(
                isinstance(item.get(key), str) and item[key].strip()
                for key in ("url", "kind", "excerpt")
            )
            for item in evidence
        )
        if not valid_evidence or (status in ("supported", "gap") and not evidence):
            errors.append(label + " has missing or malformed supporting evidence")
        if isinstance(evidence, list) and evidence:
            eligible += 1
        review = finding.get("ai_review")
        review = review if isinstance(review, dict) else {}
        if review.get("status") == "completed":
            completed += 1
        if mode == "ai" and isinstance(evidence, list) and evidence:
            if review.get("status") != "completed":
                errors.append(label + " lacks a completed AI advisory")
            elif valid_evidence:
                try:
                    review_evidence(finding, lambda _, value=review: value)
                except (ValueError, TypeError, KeyError, AttributeError):
                    errors.append(
                        label + " has an invalid AI note or evidence citation"
                    )
    for key, value in actual.items():
        if type(counts.get(key)) is not int or counts[key] != value:
            errors.append("Current finding count mismatch: " + key)
    if mode == "ai":
        ai = summary.get("ai_review")
        ai = ai if isinstance(ai, dict) else {}
        if ai.get("status") != "configured" or ai.get("requested") is not True:
            errors.append("AI was not configured and requested for this run")
        if eligible == 0:
            errors.append(
                "No evidence-bearing findings were available for AI acceptance"
            )
        if completed != eligible:
            errors.append(
                "Completed AI advisories do not match eligible current findings"
            )
        for key, value in (("eligible", eligible), ("completed", completed)):
            if type(ai.get(key)) is not int or ai[key] != value:
                errors.append("AI coverage count mismatch: " + key)
    return errors


def positive_integer(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("Value must be a positive integer")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "report",
        type=Path,
        help="Saved opportunities.json; never invokes collection or a model",
    )
    parser.add_argument("--mode", choices=("ai", "metadata"), default="ai")
    parser.add_argument("--minimum-findings", type=positive_integer, default=1)
    parser.add_argument("--max-age-hours", type=positive_integer, default=24)
    args = parser.parse_args(argv)
    try:
        with args.report.open("rb") as stream:
            raw = stream.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("Report exceeds acceptance input limit")
        summary = json.loads(raw)
        errors = assess(
            summary,
            mode=args.mode,
            minimum_findings=args.minimum_findings,
            max_age_hours=args.max_age_hours,
        )
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "automated_result": "fail",
                    "errors": [f"Cannot read acceptance report: {type(exc).__name__}"],
                    "production_approval": "not_established",
                }
            )
        )
        return 1
    print(
        json.dumps(
            {
                "automated_result": "fail" if errors else "pass",
                "mode": args.mode,
                "run_id": summary.get("run_id") if isinstance(summary, dict) else None,
                "report_sha256": hashlib.sha256(raw).hexdigest(),
                "minimum_findings": args.minimum_findings,
                "max_age_hours": args.max_age_hours,
                "errors": errors,
                "production_approval": "not_established",
                "limitations": "Checks saved evidence and advisory consistency only. Provider identity, live-call provenance, semantic quality, security disposition and actual-host approval require separate evidence.",
            },
            indent=2,
        )
    )
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
