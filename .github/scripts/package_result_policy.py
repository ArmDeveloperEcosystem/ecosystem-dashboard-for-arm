"""Shared fail-closed policy for package Test 6 decisions.

This module intentionally uses only the Python standard library so package
workflows can import it on a clean GitHub-hosted runner.
"""

from __future__ import annotations

import re

REGRESSION_STATUSES = frozenset(
    {"passed", "failed", "skipped", "deferred", "not_applicable"}
)

_MAX_MAVEN_BUILD_LOG_BYTES = 2_000_000
_MAVEN_TRANSIENT_INFRASTRUCTURE_RE = re.compile(
    r"connection reset(?: by peer)?|connection timed out|read timed out"
    r"|temporary failure in name resolution|name or service not known"
    r"|could not resolve host|unknown host|network is unreachable"
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


def classify_maven_networked_build_failure(payload: bytes | str) -> str:
    """Classify a failed Maven cache-warming build, failing closed."""

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
    if not encoded or len(encoded) > _MAX_MAVEN_BUILD_LOG_BYTES or "\x00" in text:
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
    transient_error_seen = not error_lines
    for line in error_lines:
        if not line:
            continue
        if _MAVEN_TRANSIENT_INFRASTRUCTURE_RE.search(line):
            transient_error_seen = True
            continue
        if _MAVEN_NETWORK_ERROR_WRAPPER_RE.search(line):
            continue
        return "package_failure"
    if transient_error_seen:
        return "transient_infrastructure"
    return "package_failure"

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
