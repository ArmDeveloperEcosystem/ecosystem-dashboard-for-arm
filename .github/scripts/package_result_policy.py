"""Shared fail-closed policy for package Test 6 decisions.

This module intentionally uses only the Python standard library so package
workflows can import it on a clean GitHub-hosted runner.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

REGRESSION_STATUSES = frozenset(
    {"passed", "failed", "skipped", "deferred", "not_applicable"}
)

_MAX_MAVEN_BUILD_LOG_BYTES = 2_000_000
_MAVEN_TRANSIENT_INFRASTRUCTURE_RE = re.compile(
    r"connection reset(?: by peer)?|connection timed out|read timed out"
    r"|temporary failure in name resolution|name or service not known"
    r"|could not resolve host|unknown host|unknownhostexception|network is unreachable"
    r"|no route to host|connection refused|remote host terminated the handshake"
    r"|ssl peer shut down incorrectly|premature end of content-length"
    r"|unexpected end of file from server"
    r"|status code:\s*(?:429|500|502|503|504)\b",
    re.IGNORECASE,
)
_MAVEN_PERMANENT_FAILURE_RE = re.compile(
    r"could not find artifact|failure to find .* was cached"
    r"|status code:\s*(?:400|401|403|404)\b"
    r"|unauthorized|forbidden|non-resolvable parent pom|malformed pom"
    r"|unknown lifecycle phase|no plugin found for prefix"
    r"|checksum validation failed|compilation error|cannot find symbol"
    r"|package [^\n]+ does not exist|invalid target release"
    r"|release version [^\n]+ not supported|there are test failures"
    r"|tests run:.*failures:\s*[1-9]"
    r"|failed to execute goal [^\n]*(?:maven-compiler-plugin"
    r"|maven-surefire-plugin|maven-failsafe-plugin|maven-enforcer-plugin"
    r"|maven-checkstyle-plugin)",
    re.IGNORECASE,
)
_MAVEN_RESOLUTION_ANCHOR_RE = re.compile(
    r"could not transfer artifact|transfer failed for"
    r"|failed to read artifact descriptor|could not resolve dependencies"
    r"|could not collect dependencies"
    r"|plugin .* (?:or one of its dependencies )?could not be resolved"
    r"|dependencyresolutionexception|pluginresolutionexception",
    re.IGNORECASE,
)
_MAVEN_NETWORK_ERROR_WRAPPER_RE = re.compile(
    r"could not transfer artifact|transfer failed for"
    r"|failed to read artifact descriptor|could not resolve dependencies"
    r"|could not collect dependencies"
    r"|plugin .* (?:or one of its dependencies )?could not be resolved"
    r"|dependencyresolutionexception|pluginresolutionexception"
    r"|->\s*\[help \d+\]"
    r"|to see the full stack trace|re-run maven|for more information"
    r"|https?://cwiki\.apache\.org/",
    re.IGNORECASE,
)
_MAVEN_TRANSPORT_CONTEXT_RE = re.compile(
    r"could not transfer artifact|transfer failed for"
    r"|failed to read artifact descriptor|could not resolve dependencies"
    r"|could not collect dependencies"
    r"|plugin .* (?:or one of its dependencies )?could not be resolved"
    r"|(?:unknownhost|sockettimeout|socket|connect)exception"
    r"|java\.(?:net|io)\.|org\.apache\.maven\.wagon\.",
    re.IGNORECASE,
)
_ANSI_ESCAPE_RE = re.compile(r"\033\[[0-?]*[ -/]*[@-~]")


def classify_maven_networked_build_failure(
    payload: bytes | str, *, return_code: int
) -> str:
    """Classify a failed Maven cache-warming build, failing closed."""

    if isinstance(return_code, bool) or return_code != 1:
        return "package_failure"
    if isinstance(payload, str):
        encoded = payload.encode("utf-8")
        text = payload
    elif isinstance(payload, bytes):
        encoded = payload
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            return "package_failure"
    else:
        return "package_failure"
    if not encoded or len(encoded) > _MAX_MAVEN_BUILD_LOG_BYTES:
        return "package_failure"
    text = _ANSI_ESCAPE_RE.sub("", text)
    if any(
        ord(character) < 32 and character not in "\n\r\t"
        for character in text
    ):
        return "package_failure"
    if _MAVEN_PERMANENT_FAILURE_RE.search(text):
        return "package_failure"
    if _MAVEN_TRANSIENT_INFRASTRUCTURE_RE.search(text) is None:
        return "package_failure"

    error_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.lower().startswith(("[error]", "[fatal]")):
            error_lines.append(line.split("]", 1)[1].strip())
    if not error_lines:
        return "package_failure"
    if _MAVEN_RESOLUTION_ANCHOR_RE.search("\n".join(error_lines)) is None:
        return "package_failure"

    transient_error_seen = False
    for line in error_lines:
        if not line:
            continue
        if _MAVEN_TRANSIENT_INFRASTRUCTURE_RE.search(line):
            if _MAVEN_TRANSPORT_CONTEXT_RE.search(line):
                transient_error_seen = True
                continue
            return "package_failure"
        if _MAVEN_NETWORK_ERROR_WRAPPER_RE.search(line):
            continue
        return "package_failure"
    if transient_error_seen:
        return "transient_infrastructure"
    return "package_failure"


def validate_aggregate_failure_counts(
    *,
    failed: int,
    core_failed: int,
    non_failing_regression: bool,
) -> None:
    """Reject aggregate counters that contradict a non-failing Test 6."""

    for name, value in (("failed", failed), ("core_failed", core_failed)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if not isinstance(non_failing_regression, bool):
        raise ValueError("non_failing_regression must be boolean")
    if core_failed > failed:
        raise ValueError("core_failed cannot exceed failed")
    if non_failing_regression and failed != core_failed:
        raise ValueError(
            "non-failing Test 6 requires every failure to be a baseline failure"
        )

NOT_APPLICABLE_REGRESSION_DECISIONS = frozenset(
    {
        "current_is_latest_stable",
        "no_newer_stable_available",
        "not_applicable_package_manager",
    }
)

DEFERRED_REGRESSION_DECISIONS = frozenset(
    {
        "arm64_desktop_artifact_unavailable",
        "manual_review_needed",
        "metadata_review_required",
        "next_lookup_deferred",
        "no_public_arm64_candidate",
        "runtime_validation_infrastructure_failure",
        "runtime_validation_not_automated",
        "upgrade_candidate_available",
    }
)

BASELINE_REGRESSION_DECISIONS = frozenset(
    {"baseline_failed", "baseline_install_failed"}
)

PASSED_REGRESSION_DECISIONS = frozenset(
    {
        "limited_cpu_smoke_validated",
        "next_bundle_validated",
        "next_image_validated",
        "next_install_validated",
        "next_source_preflight_validated",
        "validated_next_release",
        "validated_next_release_metadata",
    }
)

FAILED_REGRESSION_DECISIONS = frozenset(
    {
        "install_failed",
        "limited_cpu_smoke_failed",
        "next_artifact_validation_failed",
        "next_bundle_failed",
        "next_download_failed",
        "next_image_download_failed",
        "next_image_failed",
        "next_image_load_failed",
        "next_image_unknown",
        "next_install_blocked_java_runtime",
        "next_install_blocked_non_arm64_release_assets",
        "next_install_failed",
        "next_install_or_version_mismatch",
        "next_lookup_failed",
        "next_regression_failed",
        "next_runtime_failed",
        "next_source_preflight_failed",
    }
)

REGRESSION_DECISION_GROUPS = (
    NOT_APPLICABLE_REGRESSION_DECISIONS,
    DEFERRED_REGRESSION_DECISIONS,
    BASELINE_REGRESSION_DECISIONS,
    PASSED_REGRESSION_DECISIONS,
    FAILED_REGRESSION_DECISIONS,
)

if sum(len(group) for group in REGRESSION_DECISION_GROUPS) != len(
    set().union(*REGRESSION_DECISION_GROUPS)
):
    raise RuntimeError("regression decision policy groups must be disjoint")


def decision_group(decision: str) -> str:
    """Return the single approved semantic group for *decision*.

    Unknown decisions are deliberately rejected instead of being guessed from
    a raw pass/fail/skip status.
    """

    if decision in NOT_APPLICABLE_REGRESSION_DECISIONS:
        return "not_applicable"
    if decision in DEFERRED_REGRESSION_DECISIONS:
        return "deferred"
    if decision in BASELINE_REGRESSION_DECISIONS:
        return "baseline"
    if decision in PASSED_REGRESSION_DECISIONS:
        return "passed"
    if decision in FAILED_REGRESSION_DECISIONS:
        return "failed"
    raise ValueError(f"unapproved regression decision: {decision!r}")


def expected_regression_metadata(
    *, decision: str, core_failed: int
) -> dict[str, str]:
    """Return canonical semantic metadata for one approved decision."""

    if type(core_failed) is not int or core_failed < 0:
        raise ValueError("core_failed must be a non-negative integer")
    group = decision_group(decision)
    if core_failed:
        if group != "baseline":
            raise ValueError("baseline failures require an approved baseline decision")
        return {
            "status": "skipped",
            "applicability": "not_applicable",
            "reason": decision,
            "run_status": "failure",
        }
    if group == "baseline":
        raise ValueError("baseline decision contradicts five passing baseline tests")
    if group == "passed":
        return {
            "status": "passed",
            "applicability": "applicable",
            "reason": "validated",
            "run_status": "success",
        }
    if group == "failed":
        status, applicability, run_status = "failed", "applicable", "failure"
    elif group == "deferred":
        status, applicability, run_status = "deferred", "applicable", "success"
    else:
        status, applicability, run_status = (
            "not_applicable",
            "not_applicable",
            "success",
        )
    return {
        "status": status,
        "applicability": applicability,
        "reason": decision,
        "run_status": run_status,
    }


def validate_six_test_result(
    *,
    details: Sequence[Mapping[str, object]],
    passed: int,
    failed: int,
    skipped: int,
    core_failed: int,
    decision: str,
) -> str:
    """Validate one six-test result and return its required run status.

    Tests 1-5 are strict baseline checks. Test 6 may pass, fail, or use an
    approved explicit skip decision. Counters are evidence, not repair hints:
    any disagreement with the six detail records is rejected.
    """

    counters = {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "core_failed": core_failed,
    }
    for name, value in counters.items():
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if not isinstance(details, (list, tuple)) or len(details) != 6:
        raise ValueError("tests.details must contain exactly six records")

    statuses: list[str] = []
    for ordinal, detail in enumerate(details, start=1):
        if not isinstance(detail, Mapping):
            raise ValueError(f"test detail {ordinal} must be an object")
        name = detail.get("name")
        if not isinstance(name, str):
            raise ValueError(f"test detail {ordinal} name must be text")
        lowered_name = name.strip().lower()
        match = re.search(r"\btest\s*([1-6])\b", lowered_name)
        observed_ordinal = (
            6
            if lowered_name.startswith("regression applicability")
            else int(match.group(1)) if match else 0
        )
        if observed_ordinal != ordinal:
            raise ValueError(
                "test detail names must identify ordinals exactly 1 through 6"
            )
        status = detail.get("status")
        allowed = {"passed", "failed"} if ordinal <= 5 else {
            "passed",
            "failed",
            "skipped",
        }
        if not isinstance(status, str) or status not in allowed:
            raise ValueError(
                f"test detail {ordinal} has unsupported status {status!r}"
            )
        regression_fields = {
            "decision",
            "regression_result",
            "comparison",
            "current_version",
            "latest_version",
            "next_installed_version",
        }
        if ordinal <= 5 and regression_fields.intersection(detail):
            raise ValueError("regression evidence is permitted only on Test 6")
        if ordinal == 6:
            observed_decision = detail.get("decision")
            if observed_decision != decision:
                raise ValueError(
                    "Test 6 detail decision contradicts the declared decision"
                )
        statuses.append(status)

    derived = {
        "passed": statuses.count("passed"),
        "failed": statuses.count("failed"),
        "skipped": statuses.count("skipped"),
        "core_failed": statuses[:5].count("failed"),
    }
    if counters != derived:
        raise ValueError(
            f"test counters contradict detail records: {counters!r} != {derived!r}"
        )

    semantic = expected_regression_metadata(
        decision=decision, core_failed=derived["core_failed"]
    )
    test6_status = statuses[5]
    expected_test6_status = {
        "passed": "passed",
        "failed": "failed",
        "deferred": "skipped",
        "not_applicable": "skipped",
        "skipped": "skipped",
    }[semantic["status"]]
    if test6_status != expected_test6_status:
        raise ValueError(
            f"Test 6 status {test6_status!r} contradicts decision "
            f"{decision!r}"
        )
    return semantic["run_status"]


def validate_publishable_result(payload: Mapping[str, object]) -> str:
    """Validate the complete status boundary used by the final publisher."""

    if not isinstance(payload, Mapping):
        raise ValueError("package result must be an object")
    tests = payload.get("tests")
    metadata = payload.get("metadata")
    run = payload.get("run")
    if not isinstance(tests, Mapping):
        raise ValueError("tests must be an object")
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be an object")
    if not isinstance(run, Mapping):
        raise ValueError("run must be an object")

    details = tests.get("details")
    if not isinstance(details, (list, tuple)) or len(details) != 6:
        raise ValueError("tests.details must contain exactly six records")
    test6 = details[5]
    if not isinstance(test6, Mapping):
        raise ValueError("Test 6 detail must be an object")
    decision = test6.get("decision")
    if not isinstance(decision, str) or not decision:
        raise ValueError("Test 6 must contain an explicit decision")
    if metadata.get("regression_decision") != decision:
        raise ValueError("regression metadata decision contradicts Test 6")

    core_failed = metadata.get("core_failed")
    expected_run_status = validate_six_test_result(
        details=details,
        passed=tests.get("passed"),
        failed=tests.get("failed"),
        skipped=tests.get("skipped"),
        core_failed=core_failed,
        decision=decision,
    )
    semantic = expected_regression_metadata(
        decision=decision, core_failed=core_failed
    )
    for key in ("status", "applicability", "reason"):
        metadata_key = f"regression_{key}"
        if metadata.get(metadata_key) != semantic[key]:
            raise ValueError(
                f"{metadata_key} contradicts the approved Test 6 decision"
            )
    if run.get("status") != expected_run_status:
        raise ValueError("run status contradicts the six-test result")
    expected_badge = (
        "passing" if expected_run_status == "success" else "failing"
    )
    if metadata.get("badge_status") != expected_badge:
        raise ValueError("badge status contradicts the six-test result")
    return expected_run_status
