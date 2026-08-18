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

from package_result_policy import validate_publishable_result


_EXACT_JOB_URL_RE = re.compile(
    r"/actions/runs/[1-9][0-9]*/job/[1-9][0-9]*$"
)


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
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromotionError(f"invalid JSON file {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PromotionError(f"JSON file must contain an object: {path.name}")
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


def _write_text(path: Path, value: str) -> None:
    if path.is_symlink():
        raise PromotionError(f"refusing symlinked output path: {path}")
    path.write_text(value, encoding="utf-8")


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
    if _EXACT_JOB_URL_RE.search(final_url) is None:
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
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate every carried row, then materialize one complete staging set."""

    stage_root = Path(stage_root)
    _require_directory(stage_root)
    previous_dir = stage_root / "previous-production-test-results"
    candidate_dir = stage_root / "candidate-test-results"
    publish_dir = stage_root / "publish-data-test-results"
    temporary_publish_dir = stage_root / ".publish-data-test-results.tmp"
    _require_directory(previous_dir)
    _require_directory(candidate_dir)
    _clear_directory(publish_dir)
    _clear_directory(temporary_publish_dir)

    normalize_report_path = stage_root / "normalize-report.json"
    normalize_report: dict[str, Any] = {
        "blocked_slugs": {},
        "weak_urls": [],
        "duplicate_clusters": {},
        "unresolved": [],
    }
    if normalize_report_path.exists():
        normalize_report = _load_json_object(normalize_report_path)

    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise PromotionError("promotion timestamp must be timezone-aware")
    refreshed_at = timestamp.astimezone(timezone.utc).isoformat()

    previous_paths = {
        path.stem: path for path in sorted(previous_dir.glob("*.json"))
    }
    candidate_paths = {
        path.stem: path for path in sorted(candidate_dir.glob("*.json"))
    }
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
            previous_payload = _load_json_object(previous_path)
            validate_publishable_result(previous_payload)
        except (PromotionError, ValueError) as exc:
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
        payload = _load_json_object(candidate_path)
        try:
            validate_publishable_result(payload)
        except ValueError as exc:
            raise PromotionError(
                f"candidate {slug!r} violates the publishable result contract: {exc}"
            ) from exc
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
    temporary_publish_dir.rename(publish_dir)
    _write_report_files(stage_root, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage-root",
        type=Path,
        default=Path(".summary-staging"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        promote_package_results(args.stage_root)
    except PromotionError as exc:
        print(f"package result promotion error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
