#!/usr/bin/env python3
"""Fail-closed promotion of validated package results into staging."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from package_result_policy import decision_group, validate_publishable_result


_EXACT_JOB_URL_RE = re.compile(
    r"\Ahttps://github\.com/"
    r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"/actions/runs/(?P<run_id>[1-9][0-9]*)"
    r"/job/(?P<job_id>[1-9][0-9]*)\Z",
    re.ASCII,
)
_DETAIL_JOB_URL_RE = re.compile(
    _EXACT_JOB_URL_RE.pattern[:-2]
    + r"#step:[1-9][0-9]*:[1-9][0-9]*\Z",
    re.ASCII,
)
_RFC3339_RE = re.compile(
    r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z",
    re.ASCII,
)
_SLUG_RE = re.compile(
    r"\A[A-Za-z0-9](?:[A-Za-z0-9_-]{0,98}[A-Za-z0-9])?\Z",
    re.ASCII,
)
_BASELINE_NAME_RE = re.compile(r"\ATest (?P<ordinal>[1-5]) -", re.ASCII)
_RESULT_KEYS = frozenset({"schema_version", "package", "run", "tests", "metadata"})
_PACKAGE_KEYS = frozenset({"name", "version"})
_RUN_KEYS = frozenset(
    {"id", "attempt", "url", "timestamp", "status", "runner", "job_name"}
)
_RUNNER_KEYS = frozenset({"os", "arch"})
_TEST_KEYS = frozenset(
    {"passed", "failed", "skipped", "duration_seconds", "details"}
)
_STRICT_METADATA_KEYS = frozenset(
    {
        "contract_version", "package_slug", "dashboard_link", "badge_status",
        "core_failed", "batch_title", "job_url_resolution_status",
        "regression_status", "regression_decision", "regression_applicability",
        "regression_reason", "regression_note",
    }
)
_COMPATIBILITY_METADATA_KEYS = _STRICT_METADATA_KEYS - {
    "regression_status", "regression_decision",
}
_PUBLICATION_METADATA_KEYS = frozenset(
    {"production_refreshed_at", "publish_state"}
)
_REGISTRATION_MANIFEST_KEYS = frozenset(
    {
        "schema", "version", "repository", "registrations",
        "previous_registrations",
    }
)
_REGISTRATION_KEYS = frozenset(
    {
        "batch_title", "workflow_path", "run_id", "run_attempt", "job_name",
        "job_url", "job_conclusion", "job_started_at", "job_completed_at",
        "resolution_status",
    }
)
_REGISTRATION_SCHEMA = "arm-dashboard-summary-registration"
_DETAIL_REQUIRED_KEYS = frozenset(
    {"name", "status", "duration_seconds", "url"}
)
_DETAIL_ALLOWED_KEYS = _DETAIL_REQUIRED_KEYS | {
    "current_version", "latest_version", "next_installed_version", "decision",
    "regression_result", "comparison",
}
_REGRESSION_DETAIL_KEYS = _DETAIL_ALLOWED_KEYS - _DETAIL_REQUIRED_KEYS
_NORMALIZE_REPORT_KEYS = frozenset(
    {"blocked_slugs", "weak_urls", "duplicate_clusters", "unresolved"}
)
_MAX_RESULT_BYTES = 2_097_152
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 100_000


class PromotionError(ValueError):
    """Raised when package results cannot be promoted safely."""


class PromotionBlockedError(PromotionError):
    """Raised after recording a fail-closed blocked promotion report."""

    def __init__(self, report: Mapping[str, Any]):
        self.report = dict(report)
        super().__init__(
            f"{report['blocked_count']} package result(s) blocked promotion"
        )


def _reject_json_constant(value: str) -> None:
    raise PromotionError(f"unsupported JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PromotionError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _load_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PromotionError(f"result path is not a regular file: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PromotionError(f"unable to inspect JSON file {path.name}: {exc}") from exc
    if size <= 0 or size > _MAX_RESULT_BYTES:
        raise PromotionError(
            f"JSON file {path.name} has unsupported size {size}"
        )
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromotionError(f"invalid JSON file {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PromotionError(f"JSON file must contain an object: {path.name}")
    _validate_json_shape(payload)
    return payload


def _require_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise PromotionError(f"required staging directory is unsafe: {path}")


def _clear_directory(path: Path) -> None:
    if path.is_symlink():
        raise PromotionError(f"refusing symlinked publication directory: {path}")
    if path.exists():
        if not path.is_dir():
            raise PromotionError(
                f"publication destination is not a directory: {path}"
            )
        shutil.rmtree(path)


def _clear_file(path: Path) -> None:
    if path.is_symlink():
        raise PromotionError(f"refusing symlinked publication file: {path}")
    if path.exists():
        if not path.is_file():
            raise PromotionError(f"publication output is not a file: {path}")
        path.unlink()


def _write_text(path: Path, value: str) -> None:
    if path.is_symlink():
        raise PromotionError(f"refusing symlinked output path: {path}")
    path.write_text(value, encoding="utf-8")


def _validate_json_shape(payload: object) -> None:
    stack = [(payload, 1)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise PromotionError("JSON payload exceeds the node limit")
        if depth > _MAX_JSON_DEPTH:
            raise PromotionError("JSON payload exceeds the depth limit")
        if isinstance(value, Mapping):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionError(f"{label} must be an object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    required: frozenset[str],
    label: str,
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    keys = set(value)
    missing = required - keys
    unexpected = keys - required - optional
    if missing or unexpected:
        raise PromotionError(
            f"{label} has missing or unexpected keys: "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )


def _bounded_text(
    value: object,
    label: str,
    maximum: int,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise PromotionError(f"{label} must be text")
    if (not allow_empty and not value.strip()) or len(value) > maximum:
        raise PromotionError(f"{label} has an invalid length")
    if any(
        ord(character) < 32 and character not in "\n\r\t"
        for character in value
    ):
        raise PromotionError(f"{label} contains unsupported control characters")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise PromotionError(f"{label} must be a non-negative integer")
    return value


def _positive_decimal(value: object, label: str) -> str:
    text = _bounded_text(value, label, 20)
    if re.fullmatch(r"[1-9][0-9]*", text, re.ASCII) is None:
        raise PromotionError(f"{label} must be a positive decimal string")
    return text


def _timestamp(value: object, label: str) -> str:
    text = _bounded_text(value, label, 40)
    if _RFC3339_RE.fullmatch(text) is None:
        raise PromotionError(f"{label} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionError(f"{label} is not a real timestamp") from exc
    if parsed.tzinfo is None:
        raise PromotionError(f"{label} must include a timezone")
    return text


def _validate_normalize_report(payload: Mapping[str, Any]) -> None:
    _exact_keys(payload, _NORMALIZE_REPORT_KEYS, "normalize report")
    blocked = _mapping(payload["blocked_slugs"], "normalize report blocked_slugs")
    for slug, reason in blocked.items():
        if not isinstance(slug, str) or _SLUG_RE.fullmatch(slug) is None:
            raise PromotionError("normalize report contains an invalid blocked slug")
        _bounded_text(reason, f"blocked reason for {slug}", 500)
    if not isinstance(payload["weak_urls"], list):
        raise PromotionError("normalize report weak_urls must be a list")
    if not isinstance(payload["unresolved"], list):
        raise PromotionError("normalize report unresolved must be a list")
    _mapping(payload["duplicate_clusters"], "normalize report duplicate_clusters")


def _load_trusted_registrations(
    path: Path, *, expected_repository: str
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    manifest = _load_json_object(path)
    _exact_keys(
        manifest,
        _REGISTRATION_MANIFEST_KEYS,
        "trusted registration manifest",
    )
    if manifest["schema"] != _REGISTRATION_SCHEMA or manifest["version"] != 2:
        raise PromotionError(
            "trusted registration manifest version is unsupported"
        )
    if manifest["repository"] != expected_repository:
        raise PromotionError(
            "trusted registration manifest repository does not match this run"
        )

    def load_registration_set(
        value: object, label: str
    ) -> dict[str, dict[str, str]]:
        raw_registrations = _mapping(value, label)
        registrations: dict[str, dict[str, str]] = {}
        for slug, raw_registration in raw_registrations.items():
            if not isinstance(slug, str) or _SLUG_RE.fullmatch(slug) is None:
                raise PromotionError(f"{label} contains an invalid slug")
            registration = _mapping(
                raw_registration, f"{label} for {slug}"
            )
            _exact_keys(
                registration,
                _REGISTRATION_KEYS,
                f"{label} for {slug}",
            )
            batch_title = _bounded_text(
                registration["batch_title"],
                f"registration batch for {slug}",
                30,
            )
            if re.fullmatch(r"Batch [1-9][0-9]*", batch_title) is None:
                raise PromotionError(
                    f"registration batch for {slug} is malformed"
                )
            workflow_path = _bounded_text(
                registration["workflow_path"],
                f"registration workflow_path for {slug}",
                300,
            )
            if re.fullmatch(
                r"\.github/workflows/test-all-packages-batch[1-9][0-9]*\.yml",
                workflow_path,
                re.ASCII,
            ) is None:
                raise PromotionError(
                    f"registration workflow_path for {slug} is malformed"
                )
            run_id = _positive_decimal(
                registration["run_id"],
                f"registration run_id for {slug}",
            )
            run_attempt = _positive_decimal(
                registration["run_attempt"],
                f"registration run_attempt for {slug}",
            )
            job_name = _bounded_text(
                registration["job_name"],
                f"registration job_name for {slug}",
                300,
            )
            job_url = _bounded_text(
                registration["job_url"],
                f"registration job_url for {slug}",
                2_048,
            )
            job_match = _EXACT_JOB_URL_RE.fullmatch(job_url)
            if (
                job_match is None
                or job_match.group("repository") != expected_repository
                or job_match.group("run_id") != run_id
            ):
                raise PromotionError(
                    f"registration job_url for {slug} is not an exact job URL"
                )
            job_conclusion = _bounded_text(
                registration["job_conclusion"],
                f"registration job_conclusion for {slug}",
                40,
            )
            if job_conclusion not in {
                "success",
                "failure",
                "cancelled",
                "timed_out",
                "neutral",
                "skipped",
                "action_required",
                "stale",
                "startup_failure",
            }:
                raise PromotionError(
                    f"registration job_conclusion for {slug} is unsupported"
                )
            job_started_at = _timestamp(
                registration["job_started_at"],
                f"registration job_started_at for {slug}",
            )
            job_completed_at = _timestamp(
                registration["job_completed_at"],
                f"registration job_completed_at for {slug}",
            )
            started = datetime.fromisoformat(
                job_started_at.replace("Z", "+00:00")
            )
            completed = datetime.fromisoformat(
                job_completed_at.replace("Z", "+00:00")
            )
            if started > completed:
                raise PromotionError(
                    f"registration job window for {slug} is inverted"
                )
            if registration["resolution_status"] != "central_exact":
                raise PromotionError(
                    f"registration job identity for {slug} is not centrally "
                    "resolved"
                )
            registrations[slug] = {
                "batch_title": batch_title,
                "workflow_path": workflow_path,
                "run_id": run_id,
                "run_attempt": run_attempt,
                "job_name": job_name,
                "job_url": job_url,
                "job_conclusion": job_conclusion,
                "job_started_at": job_started_at,
                "job_completed_at": job_completed_at,
                "resolution_status": "central_exact",
            }
        return registrations

    current_registrations = load_registration_set(
        manifest["registrations"], "trusted current registrations"
    )
    previous_registrations = load_registration_set(
        manifest["previous_registrations"],
        "trusted previous registrations",
    )
    return current_registrations, previous_registrations


def validate_persisted_result(
    payload: Mapping[str, Any],
    *,
    expected_slug: str,
    expected_repository: str,
    expected_registration: Mapping[str, str],
    publication_role: str,
    validation_policy: str,
    allow_legacy_missing_decision: bool = False,
) -> str:
    """Validate one complete persisted row and its self-contained identity."""

    if validation_policy not in {"strict", "compatibility"}:
        raise PromotionError(
            f"unsupported result validation policy: {validation_policy!r}"
        )
    if publication_role not in {"candidate", "previous"}:
        raise PromotionError(
            f"unsupported publication role: {publication_role!r}"
        )
    registration = _mapping(
        expected_registration, f"expected registration for {expected_slug}"
    )
    _exact_keys(
        registration,
        _REGISTRATION_KEYS,
        f"expected registration for {expected_slug}",
    )
    if _SLUG_RE.fullmatch(expected_slug) is None:
        raise PromotionError(f"invalid result filename slug: {expected_slug!r}")
    if re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
        expected_repository,
        re.ASCII,
    ) is None:
        raise PromotionError("expected repository is malformed")

    result = _mapping(payload, f"result for {expected_slug}")
    _exact_keys(result, _RESULT_KEYS, "package result")
    if result["schema_version"] != "2.0":
        raise PromotionError("package result schema_version is unsupported")

    package = _mapping(result["package"], "package")
    _exact_keys(package, _PACKAGE_KEYS, "package")
    _bounded_text(package["name"], "package name", 200)
    version = _bounded_text(package["version"], "package version", 200)
    if version.strip().lower() in {"unknown", "n/a", "na", "none", "null"}:
        raise PromotionError("package version must not be a placeholder")

    run = _mapping(result["run"], "run")
    _exact_keys(run, _RUN_KEYS, "run")
    run_id = _positive_decimal(run["id"], "run.id")
    run_attempt = _positive_decimal(run["attempt"], "run.attempt")
    run_url = _bounded_text(run["url"], "run.url", 2_048)
    run_match = _EXACT_JOB_URL_RE.fullmatch(run_url)
    if (
        run_match is None
        or run_match.group("repository") != expected_repository
        or run_match.group("run_id") != run_id
    ):
        raise PromotionError(
            "run.url is not an exact job URL for the persisted run"
        )
    job_id = run_match.group("job_id")
    run_timestamp_text = _timestamp(run["timestamp"], "run.timestamp")
    run_timestamp = datetime.fromisoformat(
        run_timestamp_text.replace("Z", "+00:00")
    )
    job_started_at = datetime.fromisoformat(
        registration["job_started_at"].replace("Z", "+00:00")
    )
    job_completed_at = datetime.fromisoformat(
        registration["job_completed_at"].replace("Z", "+00:00")
    )
    if not job_started_at <= run_timestamp <= job_completed_at:
        raise PromotionError(
            "run.timestamp is outside the trusted GitHub job window"
        )
    run_status = run["status"]
    if run_status not in {"success", "failure"}:
        raise PromotionError("run.status must be success or failure")
    if run_status != registration["job_conclusion"]:
        raise PromotionError(
            "run.status does not match the trusted GitHub job conclusion"
        )
    runner = _mapping(run["runner"], "run.runner")
    _exact_keys(runner, _RUNNER_KEYS, "run.runner")
    if dict(runner) != {"os": "ubuntu-24.04", "arch": "arm64"}:
        raise PromotionError("persisted result is not native ubuntu-24.04 Arm64")
    job_name = _bounded_text(run["job_name"], "run.job_name", 300)
    if job_name != registration["job_name"]:
        raise PromotionError("run.job_name does not match trusted registration")
    if (
        run_id != registration["run_id"]
        or run_attempt != registration["run_attempt"]
        or run_url != registration["job_url"]
    ):
        raise PromotionError(
            f"{publication_role} run identity does not match trusted registration"
        )

    tests = _mapping(result["tests"], "tests")
    _exact_keys(tests, _TEST_KEYS, "tests")
    passed = _nonnegative_int(tests["passed"], "tests.passed")
    failed = _nonnegative_int(tests["failed"], "tests.failed")
    skipped = _nonnegative_int(tests["skipped"], "tests.skipped")
    _nonnegative_int(tests["duration_seconds"], "tests.duration_seconds")
    details = tests["details"]
    if not isinstance(details, list) or len(details) != 6:
        raise PromotionError("tests.details must contain exactly six records")

    normalized_details: list[Mapping[str, Any]] = []
    baseline_ordinals: set[int] = set()
    for index, raw_detail in enumerate(details, start=1):
        detail = _mapping(raw_detail, f"test detail {index}")
        _exact_keys(
            detail,
            _DETAIL_REQUIRED_KEYS,
            f"test detail {index}",
            optional=frozenset(_DETAIL_ALLOWED_KEYS - _DETAIL_REQUIRED_KEYS),
        )
        name = _bounded_text(detail["name"], f"test detail {index} name", 300)
        status = detail["status"]
        if status not in {"passed", "failed", "skipped"}:
            raise PromotionError(f"test detail {index} has invalid status")
        if index <= 5:
            if status == "skipped":
                raise PromotionError("baseline tests 1-5 must never be skipped")
            ordinal_match = _BASELINE_NAME_RE.match(name)
            if ordinal_match is None:
                raise PromotionError(
                    f"baseline detail {index} does not identify Test 1-5"
                )
            ordinal = int(ordinal_match.group("ordinal"))
            if validation_policy == "strict" and ordinal != index:
                raise PromotionError(
                    f"strict baseline detail {index} is not Test {index}"
                )
            baseline_ordinals.add(ordinal)
            if _REGRESSION_DETAIL_KEYS.intersection(detail):
                raise PromotionError(
                    "regression evidence is permitted only on Test 6"
                )
        elif not (
            name.startswith("Test 6 -") or name.startswith("Regression ")
        ):
            raise PromotionError("sixth detail is not the regression lane")
        _nonnegative_int(
            detail["duration_seconds"],
            f"test detail {index} duration_seconds",
        )
        detail_url = _bounded_text(
            detail["url"], f"test detail {index} url", 2_048
        )
        detail_match = _DETAIL_JOB_URL_RE.fullmatch(detail_url)
        if (
            detail_match is None
            or detail_match.group("repository") != expected_repository
            or detail_match.group("run_id") != run_id
            or detail_match.group("job_id") != job_id
        ):
            raise PromotionError(
                f"test detail {index} URL is not bound to the exact package job"
            )
        for key in set(detail) - _DETAIL_REQUIRED_KEYS:
            _bounded_text(
                detail[key],
                f"test detail {index} {key}",
                4_096,
                allow_empty=True,
            )
        normalized_details.append(detail)
    if baseline_ordinals != {1, 2, 3, 4, 5}:
        raise PromotionError("baseline details must identify Tests 1 through 5")

    actual_counts = {
        "passed": sum(
            detail["status"] == "passed" for detail in normalized_details
        ),
        "failed": sum(
            detail["status"] == "failed" for detail in normalized_details
        ),
        "skipped": sum(
            detail["status"] == "skipped" for detail in normalized_details
        ),
    }
    if actual_counts != {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }:
        raise PromotionError("test counters do not match six detail records")

    metadata = _mapping(result["metadata"], "metadata")
    required_metadata = (
        _STRICT_METADATA_KEYS
        if validation_policy == "strict"
        else _COMPATIBILITY_METADATA_KEYS
    )
    optional_metadata = (
        _PUBLICATION_METADATA_KEYS
        if validation_policy == "strict"
        else _PUBLICATION_METADATA_KEYS
        | frozenset({"regression_status", "regression_decision"})
    )
    _exact_keys(
        metadata,
        required_metadata,
        "metadata",
        optional=optional_metadata,
    )
    if metadata["contract_version"] != "2.0":
        raise PromotionError("metadata.contract_version is unsupported")
    slug = metadata["package_slug"]
    if not isinstance(slug, str) or slug != expected_slug:
        raise PromotionError("metadata.package_slug does not match the filename")
    if metadata["dashboard_link"] != f"/linux/opensource_packages/{slug}":
        raise PromotionError("metadata.dashboard_link is not canonical")
    if metadata["job_url_resolution_status"] != "central_exact":
        raise PromotionError("persisted row lacks an exact job URL resolution")
    if re.fullmatch(r"Batch [1-9][0-9]*", str(metadata["batch_title"])) is None:
        raise PromotionError("metadata.batch_title is malformed")
    if metadata["batch_title"] != registration["batch_title"]:
        raise PromotionError(
            "metadata.batch_title does not match trusted registration"
        )
    core_failed = _nonnegative_int(
        metadata["core_failed"], "metadata.core_failed"
    )
    baseline_failed = sum(
        detail["status"] == "failed" for detail in normalized_details[:5]
    )
    if core_failed != baseline_failed:
        raise PromotionError("core_failed contradicts baseline detail records")

    test6_status = normalized_details[5]["status"]
    detail_decision = normalized_details[5].get("decision")
    metadata_decision = metadata.get("regression_decision")
    if (
        detail_decision
        and metadata_decision
        and detail_decision != metadata_decision
    ):
        raise PromotionError("Test 6 decision contradicts regression metadata")
    decision = str(detail_decision or metadata_decision or "")
    if not decision and (
        not allow_legacy_missing_decision or test6_status != "passed"
    ):
        raise PromotionError("Test 6 must contain an explicit decision")
    if decision:
        try:
            group = decision_group(decision)
        except ValueError as exc:
            raise PromotionError(str(exc)) from exc
        expected_groups = (
            {"baseline"}
            if baseline_failed
            else {"passed"}
            if test6_status == "passed"
            else {"failed"}
            if test6_status == "failed"
            else {"deferred", "not_applicable"}
        )
        if group not in expected_groups:
            raise PromotionError("Test 6 status contradicts its decision")

    regression_status = metadata.get("regression_status")
    if regression_status is not None:
        allowed_statuses = (
            {"passed"}
            if test6_status == "passed"
            else {"failed"}
            if test6_status == "failed"
            else {"skipped", "deferred", "not_applicable"}
        )
        if regression_status not in allowed_statuses:
            raise PromotionError(
                "metadata.regression_status contradicts Test 6"
            )
    if metadata["regression_applicability"] not in {
        "applicable",
        "not_applicable",
        "not_configured",
    }:
        raise PromotionError("metadata.regression_applicability is invalid")
    _bounded_text(
        metadata["regression_reason"],
        "metadata.regression_reason",
        200,
        allow_empty=True,
    )
    _bounded_text(
        metadata["regression_note"],
        "metadata.regression_note",
        4_096,
        allow_empty=True,
    )

    expected_success = baseline_failed == 0 and test6_status != "failed"
    expected_status = "success" if expected_success else "failure"
    expected_badge = "passing" if expected_success else "failing"
    if run_status != expected_status:
        raise PromotionError("run.status contradicts the six test records")
    if metadata["badge_status"] != expected_badge:
        raise PromotionError("metadata.badge_status contradicts run.status")
    publication_keys = _PUBLICATION_METADATA_KEYS.intersection(metadata)
    if publication_role == "candidate" and publication_keys:
        raise PromotionError(
            "candidate must not contain publisher-owned metadata"
        )
    if (
        publication_role == "previous"
        and publication_keys != _PUBLICATION_METADATA_KEYS
    ):
        raise PromotionError(
            "previous row lacks complete publisher-owned metadata"
        )
    if publication_role == "previous":
        _timestamp(
            metadata["production_refreshed_at"],
            "metadata.production_refreshed_at",
        )
        if metadata["publish_state"] != "published":
            raise PromotionError("metadata.publish_state must be published")

    if validation_policy == "strict":
        try:
            validate_publishable_result(payload)
        except ValueError as exc:
            raise PromotionError(str(exc)) from exc
    return expected_status

def _candidate_publish_reason(
    slug: str,
    payload: Mapping[str, Any],
    normalize_report: Mapping[str, Any],
) -> str:
    blocked_slugs = normalize_report.get("blocked_slugs")
    if not isinstance(blocked_slugs, Mapping):
        raise PromotionError("normalize report blocked_slugs must be an object")
    blocked_reason = blocked_slugs.get(slug)
    if blocked_reason:
        return str(blocked_reason)

    run = payload.get("run")
    if not isinstance(run, Mapping):
        return "missing_run_metadata"
    final_url = str(run.get("url") or "").strip()
    if _EXACT_JOB_URL_RE.fullmatch(final_url) is None:
        return "non_exact_job_url"
    return ""


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _write_report_files(
    stage_root: Path, report: Mapping[str, Any]
) -> None:
    _write_text(
        stage_root / "publish-report.json",
        _canonical_json(report),
    )
    metrics = (
        "\n".join(
            [
                f"candidate_count={report['candidate_count']}",
                f"previous_count={report['previous_count']}",
                f"published_count={report['published_count']}",
                f"promoted_count={report['promoted_count']}",
                f"warning_count={report['warning_count']}",
                f"blocked_count={report['blocked_count']}",
            ]
        )
        + "\n"
    )
    _write_text(stage_root / "publish-metrics.env", metrics)


def promote_package_results(
    stage_root: Path,
    *,
    validation_policy: str = "strict",
    repository: str = "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate every carried row, then materialize one complete staging set."""
    if validation_policy not in {"strict", "compatibility"}:
        raise PromotionError(
            f"unsupported result validation policy: {validation_policy!r}"
        )
    if not repository:
        raise PromotionError("repository is required")
    stage_root = Path(stage_root)
    _require_directory(stage_root)
    previous_dir = stage_root / "previous-production-test-results"
    candidate_dir = stage_root / "candidate-test-results"
    publish_dir = stage_root / "publish-data-test-results"
    temporary_publish_dir = stage_root / ".publish-data-test-results.tmp"
    publish_index_path = stage_root / "publish-index.json"
    temporary_index_path = stage_root / ".publish-index.json.tmp"
    _require_directory(previous_dir)
    _require_directory(candidate_dir)
    _clear_directory(publish_dir)
    _clear_directory(temporary_publish_dir)

    _clear_file(publish_index_path)
    _clear_file(temporary_index_path)
    normalize_report_path = stage_root / "normalize-report.json"
    normalize_report: dict[str, Any] = {
        "blocked_slugs": {},
        "weak_urls": [],
        "duplicate_clusters": {},
        "unresolved": [],
    }
    if normalize_report_path.exists():
        normalize_report = _load_json_object(normalize_report_path)

    registrations, previous_registrations = _load_trusted_registrations(
        stage_root / "trusted-registrations.json",
        expected_repository=repository,
    )
    timestamp = now or datetime.now(timezone.utc)
    _validate_normalize_report(normalize_report)
    if timestamp.tzinfo is None:
        raise PromotionError("promotion timestamp must be timezone-aware")
    refreshed_at = timestamp.astimezone(timezone.utc).isoformat()

    previous_paths = {
        path.stem: path for path in sorted(previous_dir.glob("*.json"))
    }
    candidate_paths = {
        path.stem: path for path in sorted(candidate_dir.glob("*.json"))
    }
    observed_slugs = set(previous_paths) | set(candidate_paths)
    if set(registrations) != observed_slugs:
        raise PromotionError(
            "trusted registrations do not exactly cover staged package rows: "
            f"missing={sorted(observed_slugs - set(registrations))}, "
            f"unexpected={sorted(set(registrations) - observed_slugs)}"
        )
    if not set(previous_registrations) <= set(previous_paths):
        raise PromotionError(
            "trusted previous registrations contain unstaged rows: "
            f"{sorted(set(previous_registrations) - set(previous_paths))}"
        )
    promoted_payloads: dict[str, dict[str, Any]] = {}
    retained_paths: dict[str, Path] = {}
    decisions: dict[str, dict[str, str]] = {}
    blocked_count = 0
    warning_count = 0

    def retain_previous(slug: str, reason: str) -> None:
        nonlocal blocked_count, warning_count
        previous_path = previous_paths.get(slug)
        if previous_path is None:
            decisions[slug] = {
                "state": "blocked_no_previous",
                "reason": reason,
            }
            blocked_count += 1
            return
        try:
            previous_registration = previous_registrations.get(slug)
            if previous_registration is None:
                raise PromotionError(
                    "previous row lacks an API-verified historical registration"
                )
            previous_payload = _load_json_object(previous_path)
            validate_persisted_result(
                previous_payload,
                expected_slug=slug,
                expected_repository=repository,
                expected_registration=previous_registration,
                publication_role="previous",
                validation_policy=validation_policy,
                allow_legacy_missing_decision=validation_policy == "compatibility",
            )
        except PromotionError as exc:
            decisions[slug] = {
                "state": "blocked_invalid_previous",
                "reason": f"{reason}: {exc}",
            }
            blocked_count += 1
            return
        retained_paths[slug] = previous_path
        decisions[slug] = {
            "state": "retained_previous",
            "reason": reason,
        }
        warning_count += 1

    for slug, candidate_path in candidate_paths.items():
        try:
            payload = _load_json_object(candidate_path)
            validate_persisted_result(
                payload,
                expected_slug=slug,
                expected_repository=repository,
                expected_registration=registrations[slug],
                publication_role="candidate",
                validation_policy="strict",
                allow_legacy_missing_decision=False,
            )
        except PromotionError as exc:
            retain_previous(
                slug,
                f"candidate_contract_violation: {exc}",
            )
            continue
        reason = _candidate_publish_reason(slug, payload, normalize_report)
        if reason:
            retain_previous(slug, reason)
            continue

        metadata = payload["metadata"]
        metadata["production_refreshed_at"] = refreshed_at
        metadata["publish_state"] = "published"
        promoted_payloads[slug] = payload
        decisions[slug] = {
            "state": "published",
            "reason": "candidate_validated",
        }

    for slug in sorted(set(previous_paths) - set(candidate_paths)):
        retain_previous(slug, "candidate_not_emitted")

    planned_published = len(set(promoted_payloads) | set(retained_paths))
    report: dict[str, Any] = {
        "generated_at": refreshed_at,
        "candidate_count": len(candidate_paths),
        "validation_policy": validation_policy,
        "repository": repository,
        "previous_count": len(previous_paths),
        "published_count": 0 if blocked_count else planned_published,
        "promoted_count": len(promoted_payloads),
        "warning_count": warning_count,
        "blocked_count": blocked_count,
        "normalize": normalize_report,
        "decisions": decisions,
    }

    if blocked_count:
        _write_report_files(stage_root, report)
        raise PromotionBlockedError(report)

    temporary_publish_dir.mkdir()
    for slug, previous_path in retained_paths.items():
        shutil.copyfile(
            previous_path, temporary_publish_dir / f"{slug}.json"
        )
    for slug, payload in promoted_payloads.items():
        _write_text(
            temporary_publish_dir / f"{slug}.json",
            json.dumps(payload, indent=2) + "\n",
        )

    index_payload = {}
    for json_path in sorted(temporary_publish_dir.glob("*.json")):
        index_payload[json_path.stem] = _load_json_object(json_path)
    if len(index_payload) != planned_published:
        raise PromotionError(
            "publication index count contradicts the validated row set"
        )
    _write_text(temporary_index_path, _canonical_json(index_payload))

    temporary_publish_dir.rename(publish_dir)
    temporary_index_path.replace(publish_index_path)
    _write_report_files(stage_root, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage-root",
        type=Path,
        default=Path(".summary-staging"),
    )
    parser.add_argument(
        "--validation-policy",
        choices=("strict", "compatibility"),
        default="strict",
    )
    parser.add_argument(
        "--repository",
        default="ArmDeveloperEcosystem/ecosystem-dashboard-for-arm",
        help="Repository expected in every exact package job URL.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        promote_package_results(
            args.stage_root,
            validation_policy=args.validation_policy,
            repository=args.repository,
        )
    except PromotionError as exc:
        print(f"package result promotion error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
