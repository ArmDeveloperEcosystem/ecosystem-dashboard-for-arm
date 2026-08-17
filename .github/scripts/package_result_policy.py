"""Shared fail-closed policy for package Test 6 decisions.

This module intentionally uses only the Python standard library so package
workflows can import it on a clean GitHub-hosted runner.
"""

from __future__ import annotations

REGRESSION_STATUSES = frozenset(
    {"passed", "failed", "skipped", "deferred", "not_applicable"}
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
