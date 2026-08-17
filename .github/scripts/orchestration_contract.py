"""Exact-run contract for Arm64 batch orchestration and summary publication."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

BATCH_COUNT = 22
PREFETCH_BATCHES = frozenset({1, 2, 7, 12, 13, 17})
SCHEMA = "arm-dashboard-batch-orchestration"
VERSION = 2
MAX_MANIFEST_BYTES = 16_384
DISPATCH_NONCE_HEX_LENGTH = 64

_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z", re.ASCII)
_ORCHESTRATION_ID_RE = re.compile(
    r"\A(?:orchestration|manual)-[1-9][0-9]{0,19}-[1-9][0-9]{0,9}\Z",
    re.ASCII,
)
_DISPATCH_NONCE_RE = re.compile(
    rf"\A[0-9a-f]{{{DISPATCH_NONCE_HEX_LENGTH}}}\Z",
    re.ASCII,
)
_BRANCH_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,239}\Z", re.ASCII)
_REPOSITORY_RE = re.compile(
    r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/"
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z",
    re.ASCII,
)
_MANIFEST_KEYS = {
    "schema",
    "version",
    "orchestration_id",
    "expected_sha",
    "branch",
    "batches",
}
_RECORD_KEYS = {
    "batch",
    "workflow",
    "artifact",
    "dispatch_nonce",
    "run_id",
    "run_attempt",
}
_PENDING_RECORD_KEYS = {"batch", "workflow", "artifact", "dispatch_nonce"}
_INCOMPLETE_STATUSES = {
    "queued",
    "in_progress",
    "pending",
    "requested",
    "waiting",
}
_ALLOWED_CONCLUSIONS = {"success", "failure"}


class ContractError(ValueError):
    """Untrusted orchestration data does not match the exact-run contract."""


def expected_workflow(batch: int) -> str:
    _validate_batch(batch)
    return f"test-all-packages-batch{batch}.yml"


def expected_workflow_path(batch: int) -> str:
    return f".github/workflows/{expected_workflow(batch)}"


def expected_workflow_name(batch: int) -> str:
    _validate_batch(batch)
    return f"Test All Packages (Batch {batch}) on Arm64"


def expected_artifact(batch: int) -> str:
    _validate_batch(batch)
    return f"batch{batch}-test-results"


def expected_run_name(
    batch: int,
    orchestration_id: str,
    dispatch_nonce: str,
) -> str:
    batch = _validate_batch(batch)
    orchestration_id = validate_orchestration_id(orchestration_id)
    dispatch_nonce = validate_dispatch_nonce(dispatch_nonce)
    suffix = " [prefetch:none]" if batch in PREFETCH_BATCHES else ""
    return (
        f"Arm64 Batch {batch} [{orchestration_id}] "
        f"[nonce:{dispatch_nonce}]{suffix}"
    )


def validate_orchestration_id(value: object) -> str:
    if not isinstance(value, str) or not _ORCHESTRATION_ID_RE.fullmatch(value):
        raise ContractError("orchestration_id is not canonical")
    return value


def validate_dispatch_nonce(value: object) -> str:
    if not isinstance(value, str) or not _DISPATCH_NONCE_RE.fullmatch(value):
        raise ContractError(
            "dispatch_nonce must be exactly 64 lowercase hexadecimal characters"
        )
    return value


def generate_dispatch_nonce() -> str:
    nonce = secrets.token_hex(DISPATCH_NONCE_HEX_LENGTH // 2)
    return validate_dispatch_nonce(nonce)


def validate_sha(value: object, *, label: str = "expected_sha") -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ContractError(f"{label} must be one full lowercase Git SHA")
    return value


def validate_branch(value: object) -> str:
    if (
        not isinstance(value, str)
        or not _BRANCH_RE.fullmatch(value)
        or ".." in value
        or "//" in value
        or value.endswith(("/", "."))
    ):
        raise ContractError("branch is not canonical")
    return value


def validate_repository(value: object) -> str:
    if not isinstance(value, str) or not _REPOSITORY_RE.fullmatch(value):
        raise ContractError("repository is not canonical")
    return value


def validate_manifest(
    payload: object,
    *,
    expected_orchestration_id: str | None = None,
    expected_sha: str | None = None,
    expected_branch: str | None = None,
) -> dict[str, Any]:
    manifest = _require_mapping(payload, "manifest")
    _require_exact_keys(manifest, _MANIFEST_KEYS, "manifest")

    if manifest["schema"] != SCHEMA:
        raise ContractError("manifest schema is unsupported")
    version = manifest["version"]
    if isinstance(version, bool) or version != VERSION:
        raise ContractError("manifest version is unsupported")

    orchestration_id = validate_orchestration_id(manifest["orchestration_id"])
    sha = validate_sha(manifest["expected_sha"])
    branch = validate_branch(manifest["branch"])
    if expected_orchestration_id is not None:
        if orchestration_id != validate_orchestration_id(expected_orchestration_id):
            raise ContractError("manifest orchestration_id does not match this run")
    if expected_sha is not None and sha != validate_sha(expected_sha):
        raise ContractError("manifest expected_sha does not match this run")
    if expected_branch is not None and branch != validate_branch(expected_branch):
        raise ContractError("manifest branch does not match this run")

    raw_records = manifest["batches"]
    if not isinstance(raw_records, list) or len(raw_records) != BATCH_COUNT:
        raise ContractError(f"manifest must contain exactly {BATCH_COUNT} batch records")

    records: list[dict[str, Any]] = []
    run_ids: set[int] = set()
    workflows: set[str] = set()
    artifacts: set[str] = set()
    dispatch_nonces: set[str] = set()
    for expected_batch, raw_record in enumerate(raw_records, start=1):
        record = _validate_record(raw_record, expected_batch=expected_batch)
        if record["run_id"] in run_ids:
            raise ContractError("manifest contains duplicate run_id values")
        if record["workflow"] in workflows:
            raise ContractError("manifest contains duplicate workflow values")
        if record["artifact"] in artifacts:
            raise ContractError("manifest contains duplicate artifact values")
        if record["dispatch_nonce"] in dispatch_nonces:
            raise ContractError("manifest contains duplicate dispatch_nonce values")
        run_ids.add(record["run_id"])
        workflows.add(record["workflow"])
        artifacts.add(record["artifact"])
        dispatch_nonces.add(record["dispatch_nonce"])
        records.append(record)

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "orchestration_id": orchestration_id,
        "expected_sha": sha,
        "branch": branch,
        "batches": records,
    }


def build_manifest(
    *,
    orchestration_id: str,
    expected_sha: str,
    branch: str,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return validate_manifest(
        {
            "schema": SCHEMA,
            "version": VERSION,
            "orchestration_id": orchestration_id,
            "expected_sha": expected_sha,
            "branch": branch,
            "batches": [dict(record) for record in records],
        }
    )


def canonical_json(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def validate_manifest_text(
    raw: object,
    *,
    expected_sha: str,
    expected_branch: str,
    repository: str,
) -> dict[str, Any]:
    validate_repository(repository)
    if not isinstance(raw, str):
        raise ContractError("manifest input must be text")
    try:
        raw_size = len(raw.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ContractError("manifest input is not valid UTF-8") from exc
    if raw_size > MAX_MANIFEST_BYTES:
        raise ContractError("manifest input exceeds the maximum canonical size")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError("manifest input is not valid JSON") from exc
    manifest = validate_manifest(
        payload,
        expected_sha=expected_sha,
        expected_branch=expected_branch,
    )
    if raw != canonical_json(manifest):
        raise ContractError("manifest input is not canonical compact JSON")
    return manifest


def validate_sha_binding(
    *,
    expected_sha: object,
    workflow_sha: object,
    checkout_sha: object,
    remote_sha: object,
) -> str:
    expected = validate_sha(expected_sha)
    observed = {
        "workflow_sha": validate_sha(workflow_sha, label="workflow_sha"),
        "checkout_sha": validate_sha(checkout_sha, label="checkout_sha"),
        "remote_sha": validate_sha(remote_sha, label="remote_sha"),
    }
    for label, value in observed.items():
        if value != expected:
            raise ContractError(f"{label} does not match expected_sha")
    return expected


def batch_dispatch_payload(
    *,
    batch: int,
    orchestration_id: str,
    dispatch_nonce: str,
    expected_sha: str,
    branch: str,
) -> dict[str, object]:
    batch = _validate_batch(batch)
    inputs = {
        "orchestration_id": validate_orchestration_id(orchestration_id),
        "dispatch_nonce": validate_dispatch_nonce(dispatch_nonce),
        "expected_sha": validate_sha(expected_sha),
        "expected_branch": validate_branch(branch),
    }
    if batch in PREFETCH_BATCHES:
        inputs.update(
            {
                "prefetch_run_id": "",
                "prefetch_artifact_name": "",
            }
        )
    return {
        "ref": validate_branch(branch),
        "inputs": inputs,
    }


def select_exact_registration(
    payload: object,
    *,
    batch: int,
    orchestration_id: str,
    dispatch_nonce: str,
    expected_sha: str,
    branch: str,
    repository: str,
) -> int | None:
    if isinstance(payload, Mapping):
        responses = [payload]
    elif isinstance(payload, list) and payload:
        responses = payload
    else:
        raise ContractError("workflow-runs response is malformed")

    raw_runs: list[object] = []
    for page_number, raw_response in enumerate(responses, start=1):
        response = _require_mapping(
            raw_response, f"workflow-runs response page {page_number}"
        )
        page_runs = response.get("workflow_runs")
        if not isinstance(page_runs, list):
            raise ContractError("workflow-runs response is malformed")
        raw_runs.extend(page_runs)
    title = expected_run_name(batch, orchestration_id, dispatch_nonce)
    titled_runs = [
        item
        for item in raw_runs
        if isinstance(item, Mapping) and item.get("display_title") == title
    ]
    if not titled_runs:
        return None
    if len(titled_runs) != 1:
        raise ContractError("multiple runs have the exact orchestration run-name")
    run = validate_run(
        titled_runs[0],
        batch=batch,
        orchestration_id=orchestration_id,
        dispatch_nonce=dispatch_nonce,
        expected_sha=expected_sha,
        branch=branch,
        repository=repository,
        require_completed=False,
    )
    return run["id"]


def validate_run(
    payload: object,
    *,
    batch: int,
    orchestration_id: str,
    dispatch_nonce: str,
    expected_sha: str,
    branch: str,
    repository: str,
    expected_run_id: int | None = None,
    require_completed: bool,
) -> dict[str, Any]:
    run = _require_mapping(payload, "workflow run")
    run_id = _positive_int(run.get("id"), "workflow run id")
    if expected_run_id is not None and run_id != _positive_int(
        expected_run_id, "expected workflow run id"
    ):
        raise ContractError("workflow run id does not match the manifest")
    run_attempt = _positive_int(run.get("run_attempt"), "workflow run attempt")
    if run_attempt != 1:
        raise ContractError("workflow run attempt is not the original dispatch")

    run_title = expected_run_name(
        batch,
        orchestration_id,
        dispatch_nonce,
    )
    api_name = run.get("name")
    if api_name not in {expected_workflow_name(batch), run_title}:
        raise ContractError("workflow run has unexpected name")

    expected = {
        "path": expected_workflow_path(batch),
        "display_title": run_title,
        "event": "workflow_dispatch",
        "head_branch": validate_branch(branch),
        "head_sha": validate_sha(expected_sha),
    }
    for key, value in expected.items():
        if run.get(key) != value:
            raise ContractError(f"workflow run has unexpected {key}")

    repository_payload = _require_mapping(
        run.get("repository"), "workflow run repository"
    )
    if repository_payload.get("full_name") != validate_repository(repository):
        raise ContractError("workflow run belongs to an unexpected repository")

    status = run.get("status")
    conclusion = run.get("conclusion")
    if status == "completed":
        if conclusion not in _ALLOWED_CONCLUSIONS:
            raise ContractError("completed workflow run has a rejected conclusion")
    elif require_completed:
        raise ContractError("workflow run is not completed")
    elif status not in _INCOMPLETE_STATUSES or conclusion is not None:
        raise ContractError("workflow run has an invalid incomplete state")

    return {
        "id": run_id,
        "run_attempt": run_attempt,
        "status": status,
        "conclusion": conclusion,
    }


def validate_artifacts(
    payload: object,
    *,
    batch: int,
    expected_run_id: int,
) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        responses = [payload]
    elif isinstance(payload, list) and payload:
        responses = payload
    else:
        raise ContractError("artifacts response is incomplete or malformed")

    total_count: int | None = None
    artifacts: list[object] = []
    for page_number, raw_response in enumerate(responses, start=1):
        response = _require_mapping(
            raw_response, f"artifacts response page {page_number}"
        )
        page_total = response.get("total_count")
        page_artifacts = response.get("artifacts")
        if (
            isinstance(page_total, bool)
            or not isinstance(page_total, int)
            or page_total < 0
            or not isinstance(page_artifacts, list)
        ):
            raise ContractError("artifacts response is incomplete or malformed")
        if total_count is None:
            total_count = page_total
        elif page_total != total_count:
            raise ContractError("artifacts response changed during pagination")
        artifacts.extend(page_artifacts)
    if total_count != len(artifacts):
        raise ContractError("artifacts response is incomplete or malformed")

    name = expected_artifact(batch)
    matching = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, Mapping) and artifact.get("name") == name
    ]
    if len(matching) != 1:
        raise ContractError("expected batch artifact is missing or duplicated")
    artifact = matching[0]
    if artifact.get("expired") is not False:
        raise ContractError("expected batch artifact is expired")
    artifact_id = _positive_int(artifact.get("id"), "artifact id")
    workflow_run = _require_mapping(
        artifact.get("workflow_run"), "artifact workflow run"
    )
    if _positive_int(workflow_run.get("id"), "artifact workflow run id") != _positive_int(
        expected_run_id, "expected workflow run id"
    ):
        raise ContractError("artifact belongs to an unexpected workflow run")
    return {"id": artifact_id, "name": name}


def _validate_record(payload: object, *, expected_batch: int) -> dict[str, Any]:
    record = _require_mapping(payload, f"batch {expected_batch} record")
    _require_exact_keys(record, _RECORD_KEYS, f"batch {expected_batch} record")
    batch = _positive_int(record["batch"], "batch number")
    if batch != expected_batch:
        raise ContractError("manifest batch records are missing, extra, or out of order")
    workflow = record["workflow"]
    artifact = record["artifact"]
    if workflow != expected_workflow(batch):
        raise ContractError("manifest contains an unexpected workflow name")
    if artifact != expected_artifact(batch):
        raise ContractError("manifest contains an unexpected artifact name")
    return {
        "batch": batch,
        "workflow": workflow,
        "artifact": artifact,
        "dispatch_nonce": validate_dispatch_nonce(record["dispatch_nonce"]),
        "run_id": _positive_int(record["run_id"], "run_id"),
        "run_attempt": _original_run_attempt(record["run_attempt"]),
    }


def _validate_batch(value: object) -> int:
    batch = _positive_int(value, "batch number")
    if batch > BATCH_COUNT:
        raise ContractError(f"batch number must be between 1 and {BATCH_COUNT}")
    return batch


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _original_run_attempt(value: object) -> int:
    attempt = _positive_int(value, "run_attempt")
    if attempt != 1:
        raise ContractError("run_attempt must identify the original dispatch")
    return attempt


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    keys = set(value)
    if keys != expected:
        raise ContractError(
            f"{label} has missing or unexpected keys: "
            f"missing={sorted(expected - keys)!r}, extra={sorted(keys - expected)!r}"
        )


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"could not read canonical JSON from {path}") from exc


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def _write_dispatch_nonce(path: Path, nonce: str) -> None:
    nonce = validate_dispatch_nonce(nonce)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            descriptor = None
            stream.write(nonce)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ContractError("could not create dispatch nonce file") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_dispatch_nonce(path: Path) -> str:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ContractError("dispatch nonce file must be a regular file")
        if metadata.st_size != DISPATCH_NONCE_HEX_LENGTH:
            raise ContractError("dispatch nonce file has an invalid size")
        return validate_dispatch_nonce(path.read_text(encoding="ascii"))
    except OSError as exc:
        raise ContractError("could not read dispatch nonce file") from exc


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ContractError("records file must contain one JSON array")
    return [dict(_require_mapping(record, "records entry")) for record in payload]


def _pending_record(batch: int, dispatch_nonce: str) -> dict[str, Any]:
    batch = _validate_batch(batch)
    return {
        "batch": batch,
        "workflow": expected_workflow(batch),
        "artifact": expected_artifact(batch),
        "dispatch_nonce": validate_dispatch_nonce(dispatch_nonce),
    }


def _prepare_record(
    records: list[dict[str, Any]],
    *,
    batch: int,
    dispatch_nonce: str,
) -> list[dict[str, Any]]:
    record = _pending_record(batch, dispatch_nonce)
    if batch != len(records) + 1:
        raise ContractError("batch records must be prepared in canonical order")
    for existing in records:
        mapping = _require_mapping(existing, "records entry")
        if mapping.get("batch") == batch:
            raise ContractError("records file already contains this batch")
        if mapping.get("dispatch_nonce") == record["dispatch_nonce"]:
            raise ContractError("records file contains a duplicate dispatch_nonce")
    return [*records, record]


def _bind_record_run(
    records: list[dict[str, Any]],
    *,
    batch: int,
    dispatch_nonce: str,
    run_id: int,
    run_attempt: int,
) -> list[dict[str, Any]]:
    batch = _validate_batch(batch)
    dispatch_nonce = validate_dispatch_nonce(dispatch_nonce)
    run_id = _positive_int(run_id, "run_id")
    run_attempt = _original_run_attempt(run_attempt)
    if any(record.get("run_id") == run_id for record in records):
        raise ContractError("records file contains a duplicate run_id")

    updated: list[dict[str, Any]] = []
    matched = False
    for existing in records:
        record = dict(_require_mapping(existing, "records entry"))
        if record.get("batch") != batch:
            updated.append(record)
            continue
        if matched or set(record) != _PENDING_RECORD_KEYS:
            raise ContractError("batch record is not pending exact run binding")
        if record.get("dispatch_nonce") != dispatch_nonce:
            raise ContractError("pending batch record has an unexpected dispatch_nonce")
        record.update({"run_id": run_id, "run_attempt": run_attempt})
        updated.append(record)
        matched = True
    if not matched:
        raise ContractError("pending batch record is missing")
    return updated


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    context = subparsers.add_parser("validate-context")
    context.add_argument("--orchestration-id", required=True)
    context.add_argument("--expected-sha", required=True)
    context.add_argument("--branch", required=True)
    context.add_argument("--repository", required=True)

    base = subparsers.add_parser("validate-base")
    base.add_argument("--expected-sha", required=True)
    base.add_argument("--workflow-sha", required=True)
    base.add_argument("--checkout-sha", required=True)
    base.add_argument("--remote-sha", required=True)

    run_name = subparsers.add_parser("run-name")
    run_name.add_argument("--batch", type=int, required=True)
    run_name.add_argument("--orchestration-id", required=True)
    run_name.add_argument("--dispatch-nonce", required=True)

    nonce = subparsers.add_parser("generate-dispatch-nonce")
    nonce.add_argument("--output", type=Path, required=True)

    dispatch = subparsers.add_parser("batch-dispatch-payload")
    dispatch.add_argument("--batch", type=int, required=True)
    dispatch.add_argument("--orchestration-id", required=True)
    dispatch.add_argument("--dispatch-nonce-file", type=Path, required=True)
    dispatch.add_argument("--expected-sha", required=True)
    dispatch.add_argument("--branch", required=True)
    dispatch.add_argument("--output", type=Path, required=True)

    endpoint = subparsers.add_parser("runs-endpoint")
    endpoint.add_argument("--batch", type=int, required=True)
    endpoint.add_argument("--branch", required=True)
    endpoint.add_argument("--expected-sha", required=True)
    endpoint.add_argument("--repository", required=True)

    select = subparsers.add_parser("select-registration")
    select.add_argument("--payload", type=Path, required=True)
    select.add_argument("--batch", type=int, required=True)
    select.add_argument("--orchestration-id", required=True)
    select_nonce = select.add_mutually_exclusive_group(required=True)
    select_nonce.add_argument("--dispatch-nonce")
    select_nonce.add_argument("--dispatch-nonce-file", type=Path)
    select.add_argument("--expected-sha", required=True)
    select.add_argument("--branch", required=True)
    select.add_argument("--repository", required=True)

    init = subparsers.add_parser("init-records")
    init.add_argument("--output", type=Path, required=True)

    prepare = subparsers.add_parser("prepare-record")
    prepare.add_argument("--records", type=Path, required=True)
    prepare.add_argument("--batch", type=int, required=True)
    prepare.add_argument("--dispatch-nonce-file", type=Path, required=True)

    bind = subparsers.add_parser("bind-record-run")
    bind.add_argument("--records", type=Path, required=True)
    bind.add_argument("--batch", type=int, required=True)
    bind.add_argument("--dispatch-nonce-file", type=Path, required=True)
    bind.add_argument("--run-id", type=int, required=True)
    bind.add_argument("--run-attempt", type=int, required=True)

    build = subparsers.add_parser("build-manifest")
    build.add_argument("--records", type=Path, required=True)
    build.add_argument("--orchestration-id", required=True)
    build.add_argument("--expected-sha", required=True)
    build.add_argument("--branch", required=True)
    build.add_argument("--output", type=Path, required=True)

    manifest_env = subparsers.add_parser("validate-manifest-env")
    manifest_env.add_argument("--environment-variable", required=True)
    manifest_env.add_argument("--expected-sha", required=True)
    manifest_env.add_argument("--branch", required=True)
    manifest_env.add_argument("--repository", required=True)
    manifest_env.add_argument("--output", type=Path, required=True)

    manifest_context = subparsers.add_parser("manifest-context")
    manifest_context.add_argument("--manifest", type=Path, required=True)

    records = subparsers.add_parser("records-tsv")
    records.add_argument("--manifest", type=Path, required=True)

    record_id = subparsers.add_parser("record-run-id")
    record_id.add_argument("--manifest", type=Path, required=True)
    record_id.add_argument("--batch", type=int, required=True)

    record_runtime = subparsers.add_parser("record-runtime")
    record_runtime.add_argument("--manifest", type=Path, required=True)
    record_runtime.add_argument("--batch", type=int, required=True)

    run = subparsers.add_parser("validate-run")
    run.add_argument("--payload", type=Path, required=True)
    run.add_argument("--batch", type=int, required=True)
    run.add_argument("--orchestration-id", required=True)
    run.add_argument("--dispatch-nonce", required=True)
    run.add_argument("--expected-sha", required=True)
    run.add_argument("--branch", required=True)
    run.add_argument("--repository", required=True)
    run.add_argument("--expected-run-id", type=int, required=True)
    run.add_argument("--allow-incomplete", action="store_true")

    artifacts = subparsers.add_parser("validate-artifacts")
    artifacts.add_argument("--payload", type=Path, required=True)
    artifacts.add_argument("--batch", type=int, required=True)
    artifacts.add_argument("--expected-run-id", type=int, required=True)

    summary = subparsers.add_parser("summary-dispatch-payload")
    summary.add_argument("--manifest", type=Path, required=True)
    summary.add_argument("--ref", required=True)
    summary.add_argument("--output", type=Path, required=True)

    return parser


def _main(arguments: Sequence[str]) -> int:
    args = _build_parser().parse_args(arguments)

    if args.command == "validate-context":
        validate_orchestration_id(args.orchestration_id)
        validate_sha(args.expected_sha)
        validate_branch(args.branch)
        validate_repository(args.repository)
    elif args.command == "validate-base":
        validate_sha_binding(
            expected_sha=args.expected_sha,
            workflow_sha=args.workflow_sha,
            checkout_sha=args.checkout_sha,
            remote_sha=args.remote_sha,
        )
    elif args.command == "run-name":
        print(
            expected_run_name(
                args.batch,
                args.orchestration_id,
                args.dispatch_nonce,
            )
        )
    elif args.command == "generate-dispatch-nonce":
        _write_dispatch_nonce(args.output, generate_dispatch_nonce())
    elif args.command == "batch-dispatch-payload":
        _write_json(
            args.output,
            batch_dispatch_payload(
                batch=args.batch,
                orchestration_id=args.orchestration_id,
                dispatch_nonce=_load_dispatch_nonce(
                    args.dispatch_nonce_file
                ),
                expected_sha=args.expected_sha,
                branch=args.branch,
            ),
        )
    elif args.command == "runs-endpoint":
        repository = validate_repository(args.repository)
        query = urlencode(
            {
                "event": "workflow_dispatch",
                "branch": validate_branch(args.branch),
                "head_sha": validate_sha(args.expected_sha),
                "per_page": "100",
            }
        )
        print(
            f"repos/{repository}/actions/workflows/"
            f"{expected_workflow(args.batch)}/runs?{query}"
        )
    elif args.command == "select-registration":
        dispatch_nonce = (
            _load_dispatch_nonce(args.dispatch_nonce_file)
            if args.dispatch_nonce_file is not None
            else validate_dispatch_nonce(args.dispatch_nonce)
        )
        run_id = select_exact_registration(
            _load_json(args.payload),
            batch=args.batch,
            orchestration_id=args.orchestration_id,
            dispatch_nonce=dispatch_nonce,
            expected_sha=args.expected_sha,
            branch=args.branch,
            repository=args.repository,
        )
        if run_id is not None:
            print(run_id)
    elif args.command == "init-records":
        _write_json(args.output, [])
    elif args.command == "prepare-record":
        records = _read_records(args.records)
        _write_json(
            args.records,
            _prepare_record(
                records,
                batch=args.batch,
                dispatch_nonce=_load_dispatch_nonce(
                    args.dispatch_nonce_file
                ),
            ),
        )
    elif args.command == "bind-record-run":
        _write_json(
            args.records,
            _bind_record_run(
                _read_records(args.records),
                batch=args.batch,
                dispatch_nonce=_load_dispatch_nonce(
                    args.dispatch_nonce_file
                ),
                run_id=args.run_id,
                run_attempt=args.run_attempt,
            ),
        )
    elif args.command == "build-manifest":
        manifest = build_manifest(
            orchestration_id=args.orchestration_id,
            expected_sha=args.expected_sha,
            branch=args.branch,
            records=_read_records(args.records),
        )
        _write_json(args.output, manifest)
    elif args.command == "validate-manifest-env":
        raw = os.environ.get(args.environment_variable)
        if raw is None:
            raise ContractError("manifest environment variable is missing")
        manifest = validate_manifest_text(
            raw,
            expected_sha=args.expected_sha,
            expected_branch=args.branch,
            repository=args.repository,
        )
        _write_json(args.output, manifest)
    elif args.command == "manifest-context":
        manifest = validate_manifest(_load_json(args.manifest))
        print(
            f"{manifest['orchestration_id']}\t"
            f"{manifest['expected_sha']}\t{manifest['branch']}"
        )
    elif args.command == "records-tsv":
        manifest = validate_manifest(_load_json(args.manifest))
        for record in manifest["batches"]:
            print(
                f"{record['batch']}\t{record['workflow']}\t"
                f"{record['artifact']}\t{record['dispatch_nonce']}\t"
                f"{record['run_id']}\t{record['run_attempt']}"
            )
    elif args.command == "record-run-id":
        manifest = validate_manifest(_load_json(args.manifest))
        batch = _validate_batch(args.batch)
        print(manifest["batches"][batch - 1]["run_id"])
    elif args.command == "record-runtime":
        manifest = validate_manifest(_load_json(args.manifest))
        batch = _validate_batch(args.batch)
        record = manifest["batches"][batch - 1]
        print(
            f"{record['dispatch_nonce']}\t"
            f"{record['run_id']}\t{record['run_attempt']}"
        )
    elif args.command == "validate-run":
        result = validate_run(
            _load_json(args.payload),
            batch=args.batch,
            orchestration_id=args.orchestration_id,
            dispatch_nonce=args.dispatch_nonce,
            expected_sha=args.expected_sha,
            branch=args.branch,
            repository=args.repository,
            expected_run_id=args.expected_run_id,
            require_completed=not args.allow_incomplete,
        )
        print(f"{result['status']}\t{result['conclusion'] or ''}")
    elif args.command == "validate-artifacts":
        result = validate_artifacts(
            _load_json(args.payload),
            batch=args.batch,
            expected_run_id=args.expected_run_id,
        )
        print(result["id"])
    elif args.command == "summary-dispatch-payload":
        manifest = validate_manifest(_load_json(args.manifest))
        ref = validate_branch(args.ref)
        if manifest["branch"] != ref:
            raise ContractError("summary ref does not match the manifest branch")
        _write_json(
            args.output,
            {
                "ref": ref,
                "inputs": {
                    "run_manifest": canonical_json(manifest),
                    "expected_sha": manifest["expected_sha"],
                    "triggering_batch": "orchestrator",
                },
            },
        )
    else:
        raise ContractError("unsupported command")
    return 0


def main() -> int:
    try:
        return _main(sys.argv[1:])
    except ContractError as exc:
        print(f"orchestration contract rejected input: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
