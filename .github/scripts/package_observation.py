"""Strict producer and trusted-binding contract for one package workflow.

Package jobs emit an observation containing only facts they can directly know.
The exact-run parent later binds that observation to trusted GitHub API run and
job identity.  Unknown values, counter repair, fuzzy job matching, and inferred
success are intentionally forbidden.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from package_result_policy import decision_group

OBSERVATION_SCHEMA = "arm-dashboard-package-observation"
OBSERVATION_VERSION = 1
PACKAGE_RESULT_CONTRACT_VERSION = "2.0"
MAX_TEXT = 4_096
MAX_OBSERVATION_BYTES = 16_384

_SLUG_RE = re.compile(
    r"\A[A-Za-z0-9](?:[A-Za-z0-9_-]{0,98}[A-Za-z0-9])?\Z", re.ASCII
)
_DECISION_RE = re.compile(r"\A[a-z][a-z0-9_]{1,79}\Z", re.ASCII)
_REPOSITORY_RE = re.compile(
    r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/"
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z",
    re.ASCII,
)
_RFC3339_RE = re.compile(
    r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z",
    re.ASCII,
)

_OBSERVATION_KEYS = {
    "schema",
    "version",
    "contract_version",
    "package",
    "outcome",
    "tests",
    "regression",
}
_PACKAGE_KEYS = {"slug", "name", "version", "dashboard_link"}
_OUTCOME_KEYS = {"run_status", "badge_status", "core_failed"}
_TESTS_KEYS = {"passed", "failed", "skipped", "duration_seconds", "details"}
_DETAIL_KEYS = {"ordinal", "name", "status", "duration_seconds"}
_REGRESSION_KEYS = {
    "status",
    "decision",
    "applicability",
    "reason",
    "current_version",
    "latest_version",
    "next_installed_version",
    "result",
    "comparison",
}
_PLACEHOLDERS = {"", "unknown", "n/a", "na", "none", "null"}
_NARRATIVE_PLACEHOLDERS = {
    "regression result unavailable.",
    "regression comparison summary unavailable.",
    "no regression note recorded.",
}


class ObservationError(ValueError):
    """Producer data or trusted binding does not satisfy the contract."""


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ObservationError(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ObservationError(f"JSON contains unsupported constant {value!r}")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ObservationError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ObservationError(
            f"{label} has missing or unexpected keys: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _text(
    value: object,
    label: str,
    *,
    maximum: int = MAX_TEXT,
    minimum: int = 1,
) -> str:
    if not isinstance(value, str):
        raise ObservationError(f"{label} must be text")
    if value != value.strip():
        raise ObservationError(f"{label} must not have surrounding whitespace")
    if unicodedata.normalize("NFC", value) != value:
        raise ObservationError(f"{label} must use NFC Unicode normalization")
    if not minimum <= len(value) <= maximum:
        raise ObservationError(
            f"{label} length must be between {minimum} and {maximum} characters"
        )
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ObservationError(f"{label} contains a control character")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ObservationError(f"{label} must be a non-negative integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        parsed = int(value)
    else:
        raise ObservationError(f"{label} must be a non-negative integer")
    if parsed < 0 or parsed > 9_223_372_036_854_775_807:
        raise ObservationError(f"{label} is outside the supported range")
    return parsed


def _positive_int(value: object, label: str) -> int:
    parsed = _nonnegative_int(value, label)
    if parsed == 0:
        raise ObservationError(f"{label} must be positive")
    return parsed


def _slug(value: object) -> str:
    slug = _text(value, "package.slug", maximum=100)
    if _SLUG_RE.fullmatch(slug) is None:
        raise ObservationError("package.slug is not a canonical package slug")
    return slug


def _decision(value: object) -> str:
    decision = _text(value, "regression.decision", maximum=80)
    if _DECISION_RE.fullmatch(decision) is None:
        raise ObservationError("regression.decision is not canonical")
    return decision


def _status(value: object, label: str, allowed: set[str]) -> str:
    status = _text(value, label, maximum=32)
    if status not in allowed:
        raise ObservationError(f"{label} has unsupported value {status!r}")
    return status


def _meaningful_narrative(value: object, label: str, *, maximum: int) -> str:
    narrative = _text(value, label, minimum=20, maximum=maximum)
    if narrative.lower() in _NARRATIVE_PLACEHOLDERS:
        raise ObservationError(f"{label} must contain actual validation evidence")
    return narrative


def _semantic_policy(
    *, baseline_failed: int, test6_status: str, decision: str
) -> tuple[str, str, str, bool]:
    try:
        group = decision_group(decision)
    except ValueError as error:
        raise ObservationError(str(error)) from error

    if baseline_failed:
        if group != "baseline" or test6_status != "skipped":
            raise ObservationError(
                "baseline failure requires a baseline decision and skipped Test 6"
            )
        return "skipped", "not_applicable", decision, False

    if group == "baseline":
        raise ObservationError("baseline decision contradicts five passing baseline tests")

    expected_raw = {
        "passed": "passed",
        "failed": "failed",
        "deferred": "skipped",
        "not_applicable": "skipped",
    }[group]
    if test6_status != expected_raw:
        raise ObservationError(
            f"Test 6 status {test6_status!r} contradicts {group!r} decision {decision!r}"
        )
    if group == "passed":
        return "passed", "applicable", "validated", True
    if group == "failed":
        return "failed", "applicable", decision, False
    if group == "deferred":
        return "deferred", "applicable", decision, True
    return "not_applicable", "not_applicable", decision, True


def validate_observation(payload: object) -> dict[str, Any]:
    observation = _mapping(payload, "package observation")
    _exact_keys(observation, _OBSERVATION_KEYS, "package observation")
    if observation["schema"] != OBSERVATION_SCHEMA:
        raise ObservationError("package observation schema is unsupported")
    if (
        type(observation["version"]) is not int
        or observation["version"] != OBSERVATION_VERSION
    ):
        raise ObservationError("package observation version is unsupported")
    if observation["contract_version"] != PACKAGE_RESULT_CONTRACT_VERSION:
        raise ObservationError("package result contract version is unsupported")

    raw_package = _mapping(observation["package"], "package")
    _exact_keys(raw_package, _PACKAGE_KEYS, "package")
    slug = _slug(raw_package["slug"])
    package_name = _text(raw_package["name"], "package.name", maximum=200)
    version = _text(raw_package["version"], "package.version", maximum=200)
    if version.lower() in _PLACEHOLDERS:
        raise ObservationError("package.version must not be a placeholder")
    dashboard_link = f"/linux/opensource_packages/{slug}"
    if raw_package["dashboard_link"] != dashboard_link:
        raise ObservationError("package.dashboard_link is not the canonical route")

    raw_tests = _mapping(observation["tests"], "tests")
    _exact_keys(raw_tests, _TESTS_KEYS, "tests")
    raw_details = raw_tests["details"]
    if not isinstance(raw_details, list) or len(raw_details) != 6:
        raise ObservationError("tests.details must contain exactly six records")
    details: list[dict[str, Any]] = []
    for ordinal, raw_detail in enumerate(raw_details, start=1):
        detail = _mapping(raw_detail, f"tests.details[{ordinal}]")
        _exact_keys(detail, _DETAIL_KEYS, f"tests.details[{ordinal}]")
        if type(detail["ordinal"]) is not int or detail["ordinal"] != ordinal:
            raise ObservationError("test detail ordinals must be exactly 1 through 6")
        status = _status(
            detail["status"],
            f"tests.details[{ordinal}].status",
            {"passed", "failed"} if ordinal <= 5 else {"passed", "failed", "skipped"},
        )
        test_name = _text(
            detail["name"],
            f"tests.details[{ordinal}].name",
            maximum=300,
        )
        if ordinal <= 5 and not test_name.startswith(f"Test {ordinal} -"):
            raise ObservationError(f"baseline detail {ordinal} is not Test {ordinal}")
        if ordinal == 6 and not (
            test_name.startswith("Test 6 -") or test_name.startswith("Regression ")
        ):
            raise ObservationError("sixth detail is not the regression validation lane")
        details.append(
            {
                "ordinal": ordinal,
                "name": test_name,
                "status": status,
                "duration_seconds": _nonnegative_int(
                    detail["duration_seconds"],
                    f"tests.details[{ordinal}].duration_seconds",
                ),
            }
        )

    actual_counts = {
        "passed": sum(detail["status"] == "passed" for detail in details),
        "failed": sum(detail["status"] == "failed" for detail in details),
        "skipped": sum(detail["status"] == "skipped" for detail in details),
    }
    declared_counts = {
        key: _nonnegative_int(raw_tests[key], f"tests.{key}")
        for key in ("passed", "failed", "skipped")
    }
    if declared_counts != actual_counts:
        raise ObservationError("test counters do not match the six detail records")
    duration_seconds = _nonnegative_int(
        raw_tests["duration_seconds"], "tests.duration_seconds"
    )
    if duration_seconds != sum(detail["duration_seconds"] for detail in details):
        raise ObservationError("test duration does not match the six detail records")

    raw_regression = _mapping(observation["regression"], "regression")
    _exact_keys(raw_regression, _REGRESSION_KEYS, "regression")
    decision = _decision(raw_regression["decision"])
    baseline_failed = sum(detail["status"] == "failed" for detail in details[:5])
    semantic_status, applicability, reason, expected_success = _semantic_policy(
        baseline_failed=baseline_failed,
        test6_status=details[5]["status"],
        decision=decision,
    )
    if raw_regression["status"] != semantic_status:
        raise ObservationError("regression.status contradicts Test 6 evidence")
    if raw_regression["applicability"] != applicability:
        raise ObservationError("regression.applicability contradicts its decision")
    if raw_regression["reason"] != reason:
        raise ObservationError("regression.reason contradicts its decision")
    current_version = _text(
        raw_regression["current_version"], "regression.current_version", maximum=200
    )
    if current_version != version:
        raise ObservationError("regression.current_version contradicts package.version")
    latest_version = _text(
        raw_regression["latest_version"], "regression.latest_version", maximum=200
    )
    next_installed_version = _text(
        raw_regression["next_installed_version"],
        "regression.next_installed_version",
        maximum=200,
    )
    result = _meaningful_narrative(
        raw_regression["result"], "regression.result", maximum=512
    )
    comparison = _meaningful_narrative(
        raw_regression["comparison"], "regression.comparison", maximum=2_048
    )

    raw_outcome = _mapping(observation["outcome"], "outcome")
    _exact_keys(raw_outcome, _OUTCOME_KEYS, "outcome")
    run_status = _status(
        raw_outcome["run_status"], "outcome.run_status", {"success", "failure"}
    )
    badge_status = _status(
        raw_outcome["badge_status"], "outcome.badge_status", {"passing", "failing"}
    )
    core_failed = _nonnegative_int(raw_outcome["core_failed"], "outcome.core_failed")
    if core_failed != baseline_failed:
        raise ObservationError("outcome.core_failed must equal failed baseline Tests 1-5")
    expected_run_status = "success" if expected_success else "failure"
    expected_badge_status = "passing" if expected_success else "failing"
    if run_status != expected_run_status or badge_status != expected_badge_status:
        raise ObservationError("outcome contradicts strict six-test policy")

    normalized = {
        "schema": OBSERVATION_SCHEMA,
        "version": OBSERVATION_VERSION,
        "contract_version": PACKAGE_RESULT_CONTRACT_VERSION,
        "package": {
            "slug": slug,
            "name": package_name,
            "version": version,
            "dashboard_link": dashboard_link,
        },
        "outcome": {
            "run_status": expected_run_status,
            "badge_status": expected_badge_status,
            "core_failed": baseline_failed,
        },
        "tests": {
            **actual_counts,
            "duration_seconds": duration_seconds,
            "details": details,
        },
        "regression": {
            "status": semantic_status,
            "decision": decision,
            "applicability": applicability,
            "reason": reason,
            "current_version": current_version,
            "latest_version": latest_version,
            "next_installed_version": next_installed_version,
            "result": result,
            "comparison": comparison,
        },
    }
    if len(canonical_json(normalized).encode("ascii")) > MAX_OBSERVATION_BYTES:
        raise ObservationError("canonical observation exceeds the byte limit")
    return normalized


def parse_canonical_observation(raw: object) -> dict[str, Any]:
    """Parse one exact, compact observation output without losing JSON facts."""

    if not isinstance(raw, str):
        raise ObservationError("canonical observation must be text")
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ObservationError("canonical observation is not valid Unicode") from error
    if size > MAX_OBSERVATION_BYTES:
        raise ObservationError("canonical observation exceeds the byte limit")
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as error:
        raise ObservationError("observation is not valid JSON") from error
    normalized = validate_observation(payload)
    if raw != canonical_json(normalized):
        raise ObservationError("observation must be canonical compact JSON")
    return normalized


def build_observation(
    *,
    package_slug: object,
    package_name: object,
    package_version: object,
    run_status: object,
    badge_status: object,
    core_failed: object,
    tests_passed: object,
    tests_failed: object,
    tests_skipped: object,
    duration_seconds: object,
    test_details: Sequence[Mapping[str, object]],
    regression_decision: object,
    regression_current_version: object,
    regression_latest_version: object,
    regression_next_installed_version: object,
    regression_result: object,
    regression_comparison: object,
) -> dict[str, Any]:
    if len(test_details) != 6:
        raise ObservationError("test_details must contain exactly six records")
    normalized_details = [
        {
            "ordinal": ordinal,
            "name": detail.get("name"),
            "status": detail.get("status"),
            "duration_seconds": detail.get("duration_seconds"),
        }
        for ordinal, detail in enumerate(test_details, start=1)
    ]
    baseline_failed = sum(
        detail["status"] == "failed" for detail in normalized_details[:5]
    )
    decision = _decision(regression_decision)
    semantic_status, applicability, reason, _ = _semantic_policy(
        baseline_failed=baseline_failed,
        test6_status=str(normalized_details[5]["status"]),
        decision=decision,
    )
    slug = _slug(package_slug)
    raw = {
        "schema": OBSERVATION_SCHEMA,
        "version": OBSERVATION_VERSION,
        "contract_version": PACKAGE_RESULT_CONTRACT_VERSION,
        "package": {
            "slug": slug,
            "name": package_name,
            "version": package_version,
            "dashboard_link": f"/linux/opensource_packages/{slug}",
        },
        "outcome": {
            "run_status": run_status,
            "badge_status": badge_status,
            "core_failed": core_failed,
        },
        "tests": {
            "passed": tests_passed,
            "failed": tests_failed,
            "skipped": tests_skipped,
            "duration_seconds": duration_seconds,
            "details": normalized_details,
        },
        "regression": {
            "status": semantic_status,
            "decision": decision,
            "applicability": applicability,
            "reason": reason,
            "current_version": regression_current_version,
            "latest_version": regression_latest_version,
            "next_installed_version": regression_next_installed_version,
            "result": regression_result,
            "comparison": regression_comparison,
        },
    }
    return validate_observation(raw)


def bind_trusted_job(
    observation_json: object,
    *,
    repository: object,
    batch_number: object,
    run_id: object,
    run_attempt: object,
    job_id: object,
    job_name: object,
    timestamp: object,
) -> dict[str, Any]:
    """Bind producer facts to exact identity obtained by a trusted parent."""

    normalized = parse_canonical_observation(observation_json)
    repository_text = _text(repository, "repository", maximum=201)
    if _REPOSITORY_RE.fullmatch(repository_text) is None:
        raise ObservationError("repository is not owner/name")
    batch = _positive_int(batch_number, "batch_number")
    run = _positive_int(run_id, "run_id")
    attempt = _positive_int(run_attempt, "run_attempt")
    job = _positive_int(job_id, "job_id")
    job_name_text = _text(job_name, "job_name", maximum=200)
    timestamp_text = _text(timestamp, "timestamp", maximum=64)
    if _RFC3339_RE.fullmatch(timestamp_text) is None:
        raise ObservationError("timestamp must be canonical RFC3339 text")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ObservationError("timestamp must be RFC3339") from error
    if parsed_timestamp.tzinfo is None:
        raise ObservationError("timestamp must include a timezone")

    job_url = f"https://github.com/{repository_text}/actions/runs/{run}/job/{job}"
    details: list[dict[str, Any]] = []
    for detail in normalized["tests"]["details"]:
        bound = {
            "name": detail["name"],
            "status": detail["status"],
            "duration_seconds": detail["duration_seconds"],
            "url": job_url,
        }
        if detail["ordinal"] == 6:
            regression = normalized["regression"]
            bound.update(
                {
                    "current_version": regression["current_version"],
                    "latest_version": regression["latest_version"],
                    "next_installed_version": regression["next_installed_version"],
                    "decision": regression["decision"],
                    "regression_result": regression["status"],
                    "comparison": regression["comparison"],
                }
            )
        details.append(bound)

    package = normalized["package"]
    outcome = normalized["outcome"]
    tests = normalized["tests"]
    regression = normalized["regression"]
    return {
        "schema_version": PACKAGE_RESULT_CONTRACT_VERSION,
        "package": {"name": package["name"], "version": package["version"]},
        "run": {
            "id": str(run),
            "attempt": str(attempt),
            "url": job_url,
            "timestamp": timestamp_text,
            "status": outcome["run_status"],
            "runner": {"os": "ubuntu-24.04", "arch": "arm64"},
            "job_name": job_name_text,
        },
        "tests": {
            "passed": tests["passed"],
            "failed": tests["failed"],
            "skipped": tests["skipped"],
            "duration_seconds": tests["duration_seconds"],
            "details": details,
        },
        "metadata": {
            "contract_version": PACKAGE_RESULT_CONTRACT_VERSION,
            "package_slug": package["slug"],
            "dashboard_link": package["dashboard_link"],
            "badge_status": outcome["badge_status"],
            "core_failed": outcome["core_failed"],
            "batch_title": f"Batch {batch}",
            "job_url_resolution_status": "central_exact",
            "regression_status": regression["status"],
            "regression_decision": regression["decision"],
            "regression_applicability": regression["applicability"],
            "regression_reason": regression["reason"],
            "regression_note": regression["comparison"],
        },
    }


def _required_environment(name: str) -> str:
    if name not in os.environ:
        raise ObservationError(f"required environment variable {name} is missing")
    return os.environ[name]


def observation_from_environment() -> dict[str, Any]:
    details = [
        {
            "name": _required_environment(f"TEST{ordinal}_NAME"),
            "status": _required_environment(f"TEST{ordinal}_STATUS"),
            "duration_seconds": _required_environment(f"TEST{ordinal}_DURATION"),
        }
        for ordinal in range(1, 7)
    ]
    return build_observation(
        package_slug=_required_environment("PACKAGE_SLUG"),
        package_name=_required_environment("PACKAGE_NAME"),
        package_version=_required_environment("PACKAGE_VERSION"),
        run_status=_required_environment("RUN_STATUS"),
        badge_status=_required_environment("BADGE_STATUS"),
        core_failed=_required_environment("CORE_FAILED"),
        tests_passed=_required_environment("TESTS_PASSED"),
        tests_failed=_required_environment("TESTS_FAILED"),
        tests_skipped=_required_environment("TESTS_SKIPPED"),
        duration_seconds=_required_environment("DURATION_SECONDS"),
        test_details=details,
        regression_decision=_required_environment("REGRESSION_DECISION"),
        regression_current_version=_required_environment(
            "REGRESSION_CURRENT_VERSION"
        ),
        regression_latest_version=_required_environment("REGRESSION_LATEST_VERSION"),
        regression_next_installed_version=_required_environment(
            "REGRESSION_NEXT_INSTALLED_VERSION"
        ),
        regression_result=_required_environment("REGRESSION_RESULT"),
        regression_comparison=_required_environment("REGRESSION_COMPARISON"),
    )


def _emit(args: argparse.Namespace) -> int:
    observation = observation_from_environment()
    encoded = canonical_json(observation)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded + "\n", encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as stream:
            stream.write(f"package_observation_json={encoded}\n")
            stream.write(f"result_path={output}\n")
    return 0


def _validate(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if input_path.stat().st_size > MAX_OBSERVATION_BYTES + 1:
        raise ObservationError("observation file exceeds the byte limit")
    raw = input_path.read_text(encoding="utf-8")
    if not raw.endswith("\n"):
        raise ObservationError("observation file must end with one newline")
    normalized = parse_canonical_observation(raw[:-1])
    if raw != canonical_json(normalized) + "\n":
        raise ObservationError("observation file must be canonical compact JSON")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    emit = subcommands.add_parser("emit", help="emit one observation from environment")
    emit.add_argument("--output", required=True)
    emit.add_argument("--github-output")
    emit.set_defaults(handler=_emit)
    validate = subcommands.add_parser("validate", help="validate a canonical observation")
    validate.add_argument("--input", required=True)
    validate.set_defaults(handler=_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (ObservationError, OSError, UnicodeError) as error:
        print(f"package observation error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
