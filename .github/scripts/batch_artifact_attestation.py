"""Create and verify fail-closed batch result artifact attestations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from orchestration_contract import (
    ContractError,
    expected_artifact,
    expected_workflow,
    validate_branch,
    validate_dispatch_nonce,
    validate_orchestration_id,
    validate_repository,
    validate_sha,
)

SCHEMA = "arm-dashboard-batch-artifact-attestation"
VERSION = 1
SENTINEL_NAME = "batch-attestation.json"
MAX_ATTESTATION_BYTES = 131_072
MAX_NEEDS_BYTES = 2_097_152
MAX_RESULT_BYTES = 2_097_152
MAX_WORKFLOW_BYTES = 2_097_152
MAX_PACKAGES_PER_BATCH = 45

_SLUG_RE = re.compile(
    r"\A[A-Za-z0-9](?:[A-Za-z0-9_-]{0,98}[A-Za-z0-9])?\Z",
    re.ASCII,
)
_JOB_RE = re.compile(r"\Atest-[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z", re.ASCII)
_WORKFLOW_RE = re.compile(
    r"\Atest-[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.yml\Z",
    re.ASCII,
)
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z", re.ASCII)
_POSITIVE_INTEGER_RE = re.compile(r"\A[1-9][0-9]{0,19}\Z", re.ASCII)
_ATTESTATION_KEYS = {
    "schema",
    "version",
    "repository",
    "batch",
    "workflow",
    "artifact",
    "orchestration_id",
    "dispatch_nonce",
    "expected_sha",
    "branch",
    "run_id",
    "run_attempt",
    "collector",
    "packages",
}
_COLLECTOR_KEYS = {"status", "result_count"}
_PACKAGE_KEYS = {
    "job",
    "workflow",
    "package_slug",
    "result_path",
    "sha256",
}


class AttestationError(ValueError):
    """A batch artifact does not satisfy the exact collector contract."""


def canonical_json(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def create_attestation(
    *,
    results_root: Path,
    workflow_file: Path,
    batch: int,
    repository: str,
    expected_branch: str,
    current_branch: str,
    expected_sha: str,
    workflow_sha: str,
    orchestration_id: str,
    dispatch_nonce: str,
    run_id: object,
    run_attempt: object,
    artifact_name: str,
    collector_json_count: object,
    needs_json: str,
) -> dict[str, Any]:
    context = _validate_context(
        workflow_file=workflow_file,
        batch=batch,
        repository=repository,
        expected_branch=expected_branch,
        current_branch=current_branch,
        expected_sha=expected_sha,
        workflow_sha=workflow_sha,
        orchestration_id=orchestration_id,
        dispatch_nonce=dispatch_nonce,
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_name=artifact_name,
    )
    registrations = load_registrations(workflow_file, batch=batch)
    result_count = _positive_integer(
        collector_json_count, "collector_json_count"
    )
    if result_count != len(registrations):
        raise AttestationError(
            "collector_json_count does not match the exact registration count"
        )

    needs = _load_json_text(
        needs_json,
        label="needs",
        maximum_bytes=MAX_NEEDS_BYTES,
    )
    if not isinstance(needs, Mapping):
        raise AttestationError("needs must be one JSON object")
    expected_jobs = [job for job, _ in registrations]
    if set(needs) != set(expected_jobs) or len(needs) != len(expected_jobs):
        raise AttestationError(
            "needs has missing, extra, or duplicate package registrations"
        )

    root = _real_directory(results_root, "results root")
    sentinel = root / SENTINEL_NAME
    if sentinel.exists() or sentinel.is_symlink():
        raise AttestationError("attestation sentinel already exists")

    packages: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for job, workflow in registrations:
        need = needs.get(job)
        if not isinstance(need, Mapping):
            raise AttestationError(f"needs entry for {job!r} must be an object")
        if need.get("result") not in {
            "success",
            "failure",
            "cancelled",
            "skipped",
        }:
            raise AttestationError(f"needs entry for {job!r} has invalid result")
        outputs = need.get("outputs")
        if not isinstance(outputs, Mapping):
            raise AttestationError(f"needs entry for {job!r} has invalid outputs")
        emitted_slug = outputs.get("package_slug")
        slug = (
            emitted_slug.strip()
            if isinstance(emitted_slug, str) and emitted_slug.strip()
            else job.removeprefix("test-")
        )
        slug = _validate_slug(slug, f"package slug for {job}")
        if slug in seen_slugs:
            raise AttestationError("needs resolves multiple jobs to one package_slug")
        seen_slugs.add(slug)
        packages.append(
            _result_record(
                root=root,
                job=job,
                workflow=workflow,
                slug=slug,
                batch=batch,
                run_id=context["run_id"],
                run_attempt=context["run_attempt"],
            )
        )

    _validate_tree(
        root,
        package_records=packages,
        include_sentinel=False,
    )
    payload = _attestation_payload(context=context, packages=packages)
    rendered = canonical_json(payload) + "\n"
    if len(rendered.encode("utf-8")) > MAX_ATTESTATION_BYTES:
        raise AttestationError("attestation sentinel exceeds its size limit")
    _write_exclusive(sentinel, rendered)
    return payload


def verify_attestation(
    *,
    results_root: Path,
    workflow_file: Path,
    batch: int,
    repository: str,
    expected_branch: str,
    current_branch: str,
    expected_sha: str,
    workflow_sha: str,
    orchestration_id: str,
    dispatch_nonce: str,
    run_id: object,
    run_attempt: object,
    artifact_name: str,
) -> dict[str, Any]:
    context = _validate_context(
        workflow_file=workflow_file,
        batch=batch,
        repository=repository,
        expected_branch=expected_branch,
        current_branch=current_branch,
        expected_sha=expected_sha,
        workflow_sha=workflow_sha,
        orchestration_id=orchestration_id,
        dispatch_nonce=dispatch_nonce,
        run_id=run_id,
        run_attempt=run_attempt,
        artifact_name=artifact_name,
    )
    registrations = load_registrations(workflow_file, batch=batch)
    root = _real_directory(results_root, "results root")
    sentinel = _regular_file(
        root / SENTINEL_NAME,
        root=root,
        label="attestation sentinel",
        maximum_bytes=MAX_ATTESTATION_BYTES,
    )
    rendered = sentinel.read_text(encoding="utf-8")
    payload = _load_json_text(
        rendered,
        label="attestation sentinel",
        maximum_bytes=MAX_ATTESTATION_BYTES,
    )
    if rendered != canonical_json(payload) + "\n":
        raise AttestationError("attestation sentinel is not canonical JSON")
    attestation = _require_mapping(payload, "attestation sentinel")
    _require_exact_keys(attestation, _ATTESTATION_KEYS, "attestation sentinel")

    expected_scalars = {
        "schema": SCHEMA,
        "version": VERSION,
        "repository": context["repository"],
        "batch": context["batch"],
        "workflow": context["workflow"],
        "artifact": context["artifact"],
        "orchestration_id": context["orchestration_id"],
        "dispatch_nonce": context["dispatch_nonce"],
        "expected_sha": context["expected_sha"],
        "branch": context["branch"],
        "run_id": context["run_id"],
        "run_attempt": context["run_attempt"],
    }
    for key, expected in expected_scalars.items():
        if attestation.get(key) != expected:
            raise AttestationError(f"attestation has unexpected {key}")

    collector = _require_mapping(attestation.get("collector"), "collector proof")
    _require_exact_keys(collector, _COLLECTOR_KEYS, "collector proof")
    if collector.get("status") != "success":
        raise AttestationError("collector proof does not record success")
    if collector.get("result_count") != len(registrations):
        raise AttestationError("collector proof has an unexpected result count")

    raw_packages = attestation.get("packages")
    if not isinstance(raw_packages, list) or len(raw_packages) != len(registrations):
        raise AttestationError("attestation package records are incomplete")

    packages: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for (expected_job, expected_workflow_name), raw_record in zip(
        registrations, raw_packages, strict=True
    ):
        record = _require_mapping(raw_record, "attested package")
        _require_exact_keys(record, _PACKAGE_KEYS, "attested package")
        if record.get("job") != expected_job:
            raise AttestationError("attested package has an unexpected job")
        if record.get("workflow") != expected_workflow_name:
            raise AttestationError("attested package has an unexpected workflow")
        slug = _validate_slug(
            record.get("package_slug"),
            f"attested package slug for {expected_job}",
        )
        if slug in seen_slugs:
            raise AttestationError("attestation contains duplicate package slugs")
        seen_slugs.add(slug)
        expected_record = _result_record(
            root=root,
            job=expected_job,
            workflow=expected_workflow_name,
            slug=slug,
            batch=batch,
            run_id=context["run_id"],
            run_attempt=context["run_attempt"],
        )
        if dict(record) != expected_record:
            raise AttestationError("attested package result or digest does not match")
        packages.append(expected_record)

    _validate_tree(
        root,
        package_records=packages,
        include_sentinel=True,
    )
    expected_payload = _attestation_payload(context=context, packages=packages)
    if dict(attestation) != expected_payload:
        raise AttestationError("attestation sentinel does not match exact artifact")
    return expected_payload


def load_registrations(workflow_file: Path, *, batch: int) -> list[tuple[str, str]]:
    expected_name = expected_workflow(batch)
    if workflow_file.name != expected_name:
        raise AttestationError("workflow file does not match the batch number")
    workflow = _regular_file(
        workflow_file,
        root=workflow_file.parent,
        label="batch workflow",
        maximum_bytes=MAX_WORKFLOW_BYTES,
    )
    text = workflow.read_text(encoding="utf-8")
    if text.count("jobs:\n") != 1 or text.count("\n  summary:\n") != 1:
        raise AttestationError("batch workflow job structure is not canonical")
    package_region = text.split("jobs:\n", 1)[1].split("\n  summary:\n", 1)[0]
    headers = list(
        re.finditer(r"(?m)^  ([A-Za-z0-9][A-Za-z0-9_-]{0,99}):\n", package_region)
    )
    if not headers:
        raise AttestationError("batch workflow has no package registrations")

    registrations: list[tuple[str, str]] = []
    seen_workflows: set[str] = set()
    for index, header in enumerate(headers):
        job = header.group(1)
        end = headers[index + 1].start() if index + 1 < len(headers) else len(
            package_region
        )
        block = package_region[header.start() : end]
        uses = re.findall(
            r"(?m)^    uses: \./\.github/workflows/"
            r"(test-[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.yml)\s*$",
            block,
        )
        if not _JOB_RE.fullmatch(job) or len(uses) != 1:
            raise AttestationError(
                f"batch workflow has a non-package or malformed job: {job!r}"
            )
        called_workflow = uses[0]
        if not _WORKFLOW_RE.fullmatch(called_workflow):
            raise AttestationError("called package workflow name is not canonical")
        if called_workflow in seen_workflows:
            raise AttestationError("batch workflow registers one workflow more than once")
        seen_workflows.add(called_workflow)
        registrations.append((job, called_workflow))

    if len(registrations) > MAX_PACKAGES_PER_BATCH:
        raise AttestationError("batch exceeds the maximum package registration count")
    return registrations


def _validate_context(
    *,
    workflow_file: Path,
    batch: int,
    repository: str,
    expected_branch: str,
    current_branch: str,
    expected_sha: str,
    workflow_sha: str,
    orchestration_id: str,
    dispatch_nonce: str,
    run_id: object,
    run_attempt: object,
    artifact_name: str,
) -> dict[str, Any]:
    expected_workflow_name = expected_workflow(batch)
    if workflow_file.name != expected_workflow_name:
        raise AttestationError("workflow file does not match batch")
    repository = _contract(validate_repository, repository)
    branch = _contract(validate_branch, expected_branch)
    if _contract(validate_branch, current_branch) != branch:
        raise AttestationError("current branch does not match expected branch")
    sha = _contract(validate_sha, expected_sha)
    if _contract(validate_sha, workflow_sha) != sha:
        raise AttestationError("workflow SHA does not match expected SHA")
    orchestration_id = _contract(validate_orchestration_id, orchestration_id)
    dispatch_nonce = _contract(validate_dispatch_nonce, dispatch_nonce)
    parsed_run_id = _positive_integer(run_id, "run_id")
    parsed_run_attempt = _positive_integer(run_attempt, "run_attempt")
    if parsed_run_attempt != 1:
        raise AttestationError("only the original workflow run attempt is attestable")
    artifact = expected_artifact(batch)
    if artifact_name != artifact:
        raise AttestationError("artifact name does not match batch")
    return {
        "repository": repository,
        "batch": batch,
        "workflow": expected_workflow_name,
        "artifact": artifact,
        "orchestration_id": orchestration_id,
        "dispatch_nonce": dispatch_nonce,
        "expected_sha": sha,
        "branch": branch,
        "run_id": parsed_run_id,
        "run_attempt": parsed_run_attempt,
    }


def _result_record(
    *,
    root: Path,
    job: str,
    workflow: str,
    slug: str,
    batch: int,
    run_id: int,
    run_attempt: int,
) -> dict[str, Any]:
    relative = Path(f"{slug}-test-results") / f"{slug}.json"
    result = _regular_file(
        root / relative,
        root=root,
        label=f"result for {job}",
        maximum_bytes=MAX_RESULT_BYTES,
    )
    raw = result.read_bytes()
    payload = _load_json_text(
        raw.decode("utf-8"),
        label=f"result for {job}",
        maximum_bytes=MAX_RESULT_BYTES,
    )
    _validate_result_payload(
        payload,
        slug=slug,
        batch=batch,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    return {
        "job": job,
        "workflow": workflow,
        "package_slug": slug,
        "result_path": relative.as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _validate_result_payload(
    payload: object,
    *,
    slug: str,
    batch: int,
    run_id: int,
    run_attempt: int,
) -> None:
    result = _require_mapping(payload, f"result payload for {slug}")
    _require_exact_keys(
        result,
        {"schema_version", "package", "run", "tests", "metadata"},
        f"result payload for {slug}",
    )
    if result.get("schema_version") != "2.0":
        raise AttestationError(f"result for {slug} has an unsupported schema")

    package = _require_mapping(result.get("package"), f"package data for {slug}")
    for key in ("name", "version"):
        if not isinstance(package.get(key), str) or not package[key]:
            raise AttestationError(f"result for {slug} has invalid package {key}")

    run = _require_mapping(result.get("run"), f"run data for {slug}")
    if run.get("id") != str(run_id) or run.get("attempt") != str(run_attempt):
        raise AttestationError(f"result for {slug} belongs to another run")
    if run.get("status") not in {"success", "failure"}:
        raise AttestationError(f"result for {slug} has invalid run status")
    runner = _require_mapping(run.get("runner"), f"runner data for {slug}")
    if runner.get("arch") != "arm64":
        raise AttestationError(f"result for {slug} is not Arm64 evidence")

    tests = _require_mapping(result.get("tests"), f"test data for {slug}")
    for key in ("passed", "failed", "skipped", "duration_seconds"):
        _nonnegative_integer(tests.get(key), f"{slug} tests.{key}")
    details = tests.get("details")
    if not isinstance(details, list) or any(
        not isinstance(item, Mapping) for item in details
    ):
        raise AttestationError(f"result for {slug} has invalid test details")

    metadata = _require_mapping(result.get("metadata"), f"metadata for {slug}")
    if metadata.get("package_slug") != slug:
        raise AttestationError(f"result for {slug} has a mismatched package_slug")
    if metadata.get("batch_title") != f"Batch {batch}":
        raise AttestationError(f"result for {slug} has a mismatched batch title")
    if metadata.get("badge_status") not in {"passing", "failing"}:
        raise AttestationError(f"result for {slug} has invalid badge status")
    _nonnegative_integer(metadata.get("core_failed"), f"{slug} core_failed")


def _attestation_payload(
    *,
    context: Mapping[str, Any],
    packages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "repository": context["repository"],
        "batch": context["batch"],
        "workflow": context["workflow"],
        "artifact": context["artifact"],
        "orchestration_id": context["orchestration_id"],
        "dispatch_nonce": context["dispatch_nonce"],
        "expected_sha": context["expected_sha"],
        "branch": context["branch"],
        "run_id": context["run_id"],
        "run_attempt": context["run_attempt"],
        "collector": {
            "status": "success",
            "result_count": len(packages),
        },
        "packages": [dict(record) for record in packages],
    }


def _validate_tree(
    root: Path,
    *,
    package_records: Sequence[Mapping[str, Any]],
    include_sentinel: bool,
) -> None:
    allowed_files = {
        Path(str(record["result_path"]))
        for record in package_records
    }
    allowed_directories = {path.parent for path in allowed_files}
    if include_sentinel:
        allowed_files.add(Path(SENTINEL_NAME))

    observed_files: set[Path] = set()
    observed_directories: set[Path] = set()
    for entry in root.rglob("*"):
        metadata = entry.lstat()
        relative = entry.relative_to(root)
        _require_contained(root, entry.resolve(strict=False), f"artifact path {relative}")
        if stat.S_ISLNK(metadata.st_mode):
            raise AttestationError(f"artifact path must not be a symlink: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
            observed_directories.add(relative)
        elif stat.S_ISREG(metadata.st_mode):
            observed_files.add(relative)
        else:
            raise AttestationError(f"artifact path has an unsupported type: {relative}")
    if observed_files != allowed_files:
        raise AttestationError("artifact has missing, extra, or duplicate result files")
    if observed_directories != allowed_directories:
        raise AttestationError("artifact has missing or unexpected result directories")


def _real_directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AttestationError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise AttestationError(f"{label} must be a real directory")
    return resolved


def _regular_file(
    path: Path,
    *,
    root: Path,
    label: str,
    maximum_bytes: int,
) -> Path:
    root = root.resolve(strict=True)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AttestationError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AttestationError(f"{label} must be a regular file")
    _require_contained(root, resolved, label)
    if metadata.st_size < 1 or metadata.st_size > maximum_bytes:
        raise AttestationError(f"{label} has an invalid size")
    return resolved


def _require_contained(root: Path, candidate: Path, label: str) -> None:
    try:
        common = Path(os.path.commonpath((str(root), str(candidate))))
    except ValueError as exc:
        raise AttestationError(f"{label} is outside its allowed root") from exc
    if common != root:
        raise AttestationError(f"{label} is outside its allowed root")


def _write_exclusive(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise AttestationError("could not write attestation sentinel") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_json_text(raw: str, *, label: str, maximum_bytes: int) -> object:
    if not isinstance(raw, str):
        raise AttestationError(f"{label} must be text")
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise AttestationError(f"{label} is not valid UTF-8") from exc
    if size < 1 or size > maximum_bytes:
        raise AttestationError(f"{label} has an invalid size")

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise AttestationError(f"{label} contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs_hook,
            parse_constant=lambda value: (_ for _ in ()).throw(
                AttestationError(f"{label} contains non-finite JSON")
            ),
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AttestationError(f"{label} is not valid JSON") from exc


def _validate_slug(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SLUG_RE.fullmatch(value):
        raise AttestationError(f"{label} is not a canonical package slug")
    return value


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise AttestationError(f"{label} must be a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and _POSITIVE_INTEGER_RE.fullmatch(value):
        parsed = int(value)
    else:
        raise AttestationError(f"{label} must be a positive integer")
    if parsed < 1:
        raise AttestationError(f"{label} must be a positive integer")
    return parsed


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AttestationError(f"{label} must be a nonnegative integer")
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AttestationError(f"{label} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise AttestationError(f"{label} has missing or unexpected keys")


def _contract(function: Any, value: object) -> Any:
    try:
        return function(value)
    except ContractError as exc:
        raise AttestationError(str(exc)) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--results-root", type=Path, required=True)
        command.add_argument("--workflow-file", type=Path, required=True)
        command.add_argument("--batch", type=int, required=True)
        command.add_argument("--repository", required=True)
        command.add_argument("--expected-branch", required=True)
        command.add_argument("--current-branch", required=True)
        command.add_argument("--expected-sha", required=True)
        command.add_argument("--workflow-sha", required=True)
        command.add_argument("--orchestration-id", required=True)
        command.add_argument("--dispatch-nonce", required=True)
        command.add_argument("--run-id", required=True)
        command.add_argument("--run-attempt", required=True)
        command.add_argument("--artifact-name", required=True)
        if name == "create":
            command.add_argument("--collector-json-count", required=True)
            command.add_argument(
                "--needs-environment-variable",
                required=True,
            )
    return parser


def _main(arguments: Sequence[str]) -> int:
    args = _build_parser().parse_args(arguments)
    common = {
        "results_root": args.results_root,
        "workflow_file": args.workflow_file,
        "batch": args.batch,
        "repository": args.repository,
        "expected_branch": args.expected_branch,
        "current_branch": args.current_branch,
        "expected_sha": args.expected_sha,
        "workflow_sha": args.workflow_sha,
        "orchestration_id": args.orchestration_id,
        "dispatch_nonce": args.dispatch_nonce,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
        "artifact_name": args.artifact_name,
    }
    if args.command == "create":
        needs_json = os.environ.get(args.needs_environment_variable)
        if needs_json is None:
            raise AttestationError("needs environment variable is missing")
        create_attestation(
            **common,
            collector_json_count=args.collector_json_count,
            needs_json=needs_json,
        )
    else:
        verify_attestation(**common)
    return 0


def main() -> int:
    try:
        return _main(sys.argv[1:])
    except (AttestationError, ContractError, OSError, UnicodeError) as exc:
        print(f"batch attestation rejected input: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
