"""Fail-closed contracts for exact-run Arm64 result aggregation.

This module is intentionally independent of the production orchestrator.  It
defines the data boundary that a later cutover must satisfy before downloaded
batch results can be considered publishable evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shlex
import stat
import struct
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import yaml

from package_result_policy import (
    BASELINE_REGRESSION_DECISIONS as _BASELINE_REGRESSION_DECISIONS,
    DEFERRED_REGRESSION_DECISIONS as _DEFERRED_REGRESSION_DECISIONS,
    FAILED_REGRESSION_DECISIONS as _FAILED_REGRESSION_DECISIONS,
    NOT_APPLICABLE_REGRESSION_DECISIONS as _NOT_APPLICABLE_REGRESSION_DECISIONS,
    PASSED_REGRESSION_DECISIONS as _PASSED_REGRESSION_DECISIONS,
    REGRESSION_DECISION_GROUPS as _REGRESSION_DECISION_GROUPS,
    REGRESSION_STATUSES as _REGRESSION_STATUSES,
)

MANIFEST_SCHEMA = "arm-dashboard-exact-run-manifest"
MANIFEST_VERSION = 1
BATCH_ATTESTATION_SCHEMA = "arm-dashboard-batch-artifact-attestation"
BATCH_ATTESTATION_VERSION = 2
AGGREGATE_ATTESTATION_SCHEMA = "arm-dashboard-aggregate-attestation"
AGGREGATE_ATTESTATION_VERSION = 1
BATCH_ATTESTATION_NAME = "batch-attestation.json"

MAX_BATCHES = 100
MAX_PACKAGES_PER_BATCH = 100
TARGET_PACKAGES_PER_BATCH = 45
MAX_MANIFEST_BYTES = 2_097_152
MAX_BATCH_ATTESTATION_BYTES = 262_144
MAX_RESULT_BYTES = 2_097_152
MAX_BATCH_BYTES = 134_217_728
MAX_BATCH_ENTRIES = (MAX_PACKAGES_PER_BATCH * 2) + 1
MAX_ZIP_CENTRAL_DIRECTORY_BYTES = 262_144
MAX_ZIP_MEMBER_NAME_BYTES = 512
MAX_ZIP_EXTRA_BYTES = 4_096
MAX_ZIP_COMMENT_BYTES = 1_024
MAX_DETAIL_TEXT = 4_096
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 100_000
MAX_INTEGER = 9_223_372_036_854_775_807
MAX_API_PAGES = 20
MAX_API_ITEMS = 5_000
MAX_ORCHESTRATION_WINDOW_SECONDS = 86_400
MAX_GIT_TREE_BYTES = 4_194_304
MAX_WORKFLOW_FILES = 4_096
MAX_WORKFLOW_FILE_BYTES = 2_097_152
MAX_WORKFLOW_SNAPSHOT_BYTES = 67_108_864

_SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z", re.ASCII)
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z", re.ASCII)
_DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z", re.ASCII)
_NONCE_RE = re.compile(r"\A[0-9a-f]{64}\Z", re.ASCII)
_REPOSITORY_RE = re.compile(
    r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/"
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z",
    re.ASCII,
)
_BRANCH_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/-]{0,239}\Z", re.ASCII)
_ORCHESTRATION_RE = re.compile(
    r"\A(?:orchestration|manual)-[1-9][0-9]{0,19}-[1-9][0-9]{0,9}\Z",
    re.ASCII,
)
_SLUG_RE = re.compile(
    r"\A[A-Za-z0-9](?:[A-Za-z0-9_-]{0,98}[A-Za-z0-9])?\Z",
    re.ASCII,
)
_JOB_RE = re.compile(r"\Atest-[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z", re.ASCII)
_CALLED_JOB_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_-]{0,99}\Z", re.ASCII)
_WORKFLOW_FILE_RE = re.compile(
    r"\Atest-[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.yml\Z",
    re.ASCII,
)
_BATCH_FILE_RE = re.compile(r"\Atest-all-packages-batch([1-9][0-9]*)\.yml\Z")
_PREFETCH_BATCHES = frozenset({1, 2, 7, 12, 13, 17})
_PREFETCH_INPUTS = frozenset({"prefetch_run_id", "prefetch_artifact_name"})
_PREFETCH_JOB_BINDINGS = {
    1: frozenset({"test-spark", "test-nifi"}),
    2: frozenset({"test-pinot"}),
    7: frozenset({"test-hive"}),
    12: frozenset({"test-hadoop", "test-dolphinscheduler"}),
    13: frozenset({"test-storm"}),
    17: frozenset({"test-druid"}),
}
_PREFETCH_FORWARDING = {
    "prefetch_run_id": "${{ inputs.prefetch_run_id || '' }}",
    "prefetch_artifact_name": "${{ inputs.prefetch_artifact_name || '' }}",
}

_ACTION_OUTPUT_VALUE_RE = re.compile(
    r"^\$\{\{\s*steps\.(?P<step>[A-Za-z0-9_-]+)\.outputs\."
    r"(?P<output>[A-Za-z0-9_-]+)\s*\}\}$",
    re.ASCII,
)
_RFC3339_RE = re.compile(
    r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z",
    re.ASCII,
)
_RUN_URL_RE = re.compile(
    r"\Ahttps://github\.com/(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"/actions/runs/(?P<run_id>[1-9][0-9]*)/job/(?P<job_id>[1-9][0-9]*)"
    r"(?:#step:[1-9][0-9]*:[1-9][0-9]*)?\Z",
    re.ASCII,
)
_IMMUTABLE_ACTION_RE = re.compile(
    r"\A[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    r"(?:/[A-Za-z0-9_.-]+)*@[0-9a-f]{40}\Z",
    re.ASCII,
)
_IMMUTABLE_DOCKER_RE = re.compile(r"\Adocker://[^@\s]+@sha256:[0-9a-f]{64}\Z", re.ASCII)

_MANIFEST_KEYS = {
    "schema",
    "version",
    "repository",
    "branch",
    "head_sha",
    "topology_sha256",
    "orchestration_id",
    "created_at",
    "batches",
}
_MANIFEST_BATCH_KEYS = {
    "batch",
    "workflow_path",
    "workflow_name",
    "artifact_name",
    "dispatch_nonce",
    "run",
    "jobs",
    "artifact",
}
_RUN_KEYS = {
    "id",
    "attempt",
    "workflow_path",
    "workflow_name",
    "display_title",
    "event",
    "head_branch",
    "head_sha",
    "status",
    "conclusion",
    "created_at",
    "updated_at",
}
_ARTIFACT_KEYS = {
    "id",
    "name",
    "size_in_bytes",
    "digest",
    "created_at",
    "expired",
    "workflow_run_id",
}
_JOB_KEYS = {
    "registration_job",
    "workflow_path",
    "package_slug",
    "id",
    "name",
    "run_id",
    "run_attempt",
    "status",
    "conclusion",
    "started_at",
    "completed_at",
    "html_url",
}
_BATCH_ATTESTATION_KEYS = {
    "schema",
    "version",
    "repository",
    "orchestration_id",
    "batch",
    "workflow_path",
    "artifact_name",
    "dispatch_nonce",
    "branch",
    "head_sha",
    "run_id",
    "run_attempt",
    "collector",
    "packages",
}
_COLLECTOR_KEYS = {"status", "result_count"}
_ATTESTED_PACKAGE_KEYS = {
    "job",
    "workflow_path",
    "package_slug",
    "result_path",
    "sha256",
}
_BATCH_PROOF_KEYS = {
    "batch",
    "run_id",
    "run_attempt",
    "artifact_id",
    "artifact_digest",
    "archive_sha256",
    "attestation_sha256",
    "packages",
}
_AGGREGATE_PACKAGE_PROOF_KEYS = _ATTESTED_PACKAGE_KEYS | {
    "job_id",
    "job_name",
    "job_url",
    "run_status",
    "badge_status",
}
_RESULT_KEYS = {"schema_version", "package", "run", "tests", "metadata"}
_PACKAGE_KEYS = {"name", "version"}
_RESULT_RUN_KEYS = {"id", "attempt", "url", "timestamp", "status", "runner", "job_name"}
_RUNNER_KEYS = {"os", "arch"}
_TEST_KEYS = {"passed", "failed", "skipped", "duration_seconds", "details"}
_METADATA_KEYS = {
    "contract_version",
    "package_slug",
    "dashboard_link",
    "badge_status",
    "core_failed",
    "batch_title",
    "job_url_resolution_status",
    "regression_status",
    "regression_decision",
    "regression_applicability",
    "regression_reason",
    "regression_note",
}
_DETAIL_REQUIRED_KEYS = {"name", "status", "duration_seconds", "url"}
_DETAIL_ALLOWED_KEYS = _DETAIL_REQUIRED_KEYS | {
    "current_version",
    "latest_version",
    "next_installed_version",
    "decision",
    "regression_result",
    "comparison",
}
class ContractError(ValueError):
    """Untrusted result data does not satisfy the aggregation contract."""


class _UniqueSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent: object, index: object) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            raise ContractError("YAML aliases are not accepted in workflow contracts")
        return super().compose_node(parent, index)

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[object, object]:
        if not isinstance(node, yaml.MappingNode):
            raise ContractError("YAML mapping node is malformed")
        result: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as exc:
                raise ContractError("YAML mapping key must be a scalar") from exc
            if duplicate:
                raise ContractError(f"YAML mapping contains duplicate key {key!r}")
            try:
                result[key] = self.construct_object(value_node, deep=deep)
            except TypeError as exc:
                raise ContractError("YAML mapping key must be hashable") from exc
        return result


_UniqueSafeLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern)
        for tag, pattern in resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_UniqueSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$", re.ASCII),
    list("tTfF"),
)


@dataclass(frozen=True)
class PackageRegistration:
    job: str
    called_job: str
    workflow_path: str
    package_slug: str


@dataclass(frozen=True)
class BatchDefinition:
    batch: int
    workflow_path: str
    workflow_name: str
    artifact_name: str
    packages: tuple[PackageRegistration, ...]
    external_actions: tuple[str, ...]
    local_actions: tuple[str, ...]


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def discover_topology(repository_root: Path) -> tuple[BatchDefinition, ...]:
    root = _real_directory(repository_root, "repository root")
    workflow_root = _real_directory(root / ".github" / "workflows", "workflow root")
    candidates: list[tuple[int, Path]] = []
    for path in workflow_root.iterdir():
        match = _BATCH_FILE_RE.fullmatch(path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    candidates.sort()
    if not candidates or len(candidates) > MAX_BATCHES:
        raise ContractError("batch topology has an invalid number of workflows")
    if [number for number, _ in candidates] != list(range(1, len(candidates) + 1)):
        raise ContractError("batch workflow numbers must be contiguous from 1")

    topology: list[BatchDefinition] = []
    seen_jobs: set[str] = set()
    seen_workflows: set[str] = set()
    seen_slugs: set[str] = set()
    for batch, path in candidates:
        definition = _parse_batch_workflow(path, batch=batch, root=root)
        for package in definition.packages:
            if package.job in seen_jobs:
                raise ContractError(
                    f"package job is registered more than once: {package.job}"
                )
            if package.workflow_path in seen_workflows:
                raise ContractError(
                    f"package workflow is registered more than once: {package.workflow_path}"
                )
            if package.package_slug in seen_slugs:
                raise ContractError(
                    f"package slug is registered more than once: {package.package_slug}"
                )
            seen_jobs.add(package.job)
            seen_workflows.add(package.workflow_path)
            seen_slugs.add(package.package_slug)
        topology.append(definition)
    package_workflows = {
        f".github/workflows/{path.name}"
        for path in workflow_root.iterdir()
        if path.name.startswith("test-")
        and path.name.endswith(".yml")
        and not path.name.startswith("test-all-packages-")
    }
    if seen_workflows != package_workflows:
        missing = sorted(package_workflows - seen_workflows)
        unknown = sorted(seen_workflows - package_workflows)
        raise ContractError(
            "package workflows must be registered exactly once: "
            f"unregistered={missing}, unknown={unknown}"
        )
    return tuple(topology)


def discover_topology_at_commit(
    repository_root: Path, expected_sha: str
) -> tuple[BatchDefinition, ...]:
    """Discover workflow topology from immutable Git objects at one commit."""
    root = _real_directory(repository_root, "repository root")
    expected = _sha(expected_sha, "expected_sha")
    environment = _git_environment(root)
    try:
        tree = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                expected,
                "--",
                ".github/workflows",
                ".github/actions",
            ],
            check=True,
            capture_output=True,
            timeout=20,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError(
            "could not read workflow/action topology from exact commit"
        ) from exc
    if len(tree.stdout) > MAX_GIT_TREE_BYTES:
        raise ContractError("Git topology tree exceeds the resource limit")

    entries: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    seen_casefolded: set[str] = set()
    for raw_record in tree.stdout.split(b"\0"):
        if not raw_record:
            continue
        try:
            raw_header, raw_path = raw_record.split(b"\t", 1)
            mode, object_type, object_id = raw_header.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ContractError("Git workflow tree contains a malformed entry") from exc
        parts = PurePosixPath(path).parts
        safe_workflow = len(parts) == 3 and parts[:2] == (
            ".github",
            "workflows",
        )
        safe_action = 3 <= len(parts) <= 12 and parts[:2] == (".github", "actions")
        if (
            mode not in {"100644", "100755"}
            or object_type != "blob"
            or not _SHA_RE.fullmatch(object_id)
            or not (safe_workflow or safe_action)
            or any(part in {"", ".", ".."} for part in parts)
            or any(len(part.encode("utf-8")) > 255 for part in parts)
        ):
            raise ContractError("Git topology tree contains an unsafe entry")
        normalized = unicodedata.normalize("NFC", path).casefold()
        if path in seen_paths or normalized in seen_casefolded:
            raise ContractError("Git topology tree contains duplicate paths")
        seen_paths.add(path)
        seen_casefolded.add(normalized)
        entries.append((path, object_id))
    if not entries or len(entries) > MAX_WORKFLOW_FILES:
        raise ContractError("Git topology tree has an invalid number of files")

    try:
        size_check = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "cat-file",
                "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            ],
            input="".join(f"{object_id}\n" for _, object_id in entries),
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError("could not bound workflow Git objects") from exc
    if len(size_check.stdout.encode("utf-8")) > 1_048_576:
        raise ContractError("Git object metadata exceeds the resource limit")
    size_lines = size_check.stdout.splitlines()
    if len(size_lines) != len(entries):
        raise ContractError("Git object metadata is incomplete")
    object_sizes: list[int] = []
    total_size = 0
    for (_, expected_object_id), line in zip(entries, size_lines, strict=True):
        fields = line.split(" ")
        if (
            len(fields) != 3
            or fields[0] != expected_object_id
            or fields[1] != "blob"
            or not re.fullmatch(r"(?:0|[1-9][0-9]*)", fields[2], re.ASCII)
        ):
            raise ContractError("Git object metadata is malformed")
        size = int(fields[2])
        if size > MAX_WORKFLOW_FILE_BYTES:
            raise ContractError("workflow/action file exceeds the resource limit")
        total_size += size
        if total_size > MAX_WORKFLOW_SNAPSHOT_BYTES:
            raise ContractError("workflow/action snapshot exceeds the resource limit")
        object_sizes.append(size)

    with tempfile.TemporaryDirectory(prefix="exact-topology-") as temporary:
        snapshot = Path(temporary)
        workflow_root = snapshot / ".github" / "workflows"
        workflow_root.mkdir(parents=True, mode=0o700)
        for (path, object_id), expected_size in zip(entries, object_sizes, strict=True):
            try:
                blob = subprocess.run(
                    ["git", "-C", str(root), "cat-file", "blob", object_id],
                    check=True,
                    capture_output=True,
                    timeout=10,
                    env=environment,
                ).stdout
            except (OSError, subprocess.SubprocessError) as exc:
                raise ContractError("could not read a workflow Git object") from exc
            if len(blob) != expected_size:
                raise ContractError("workflow/action Git object size changed")
            target = snapshot / path
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(target, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
        return discover_topology(snapshot)


def topology_payload(topology: Sequence[BatchDefinition]) -> dict[str, Any]:
    external_actions = sorted(
        {reference for batch in topology for reference in batch.external_actions}
    )
    local_actions = sorted(
        {reference for batch in topology for reference in batch.local_actions}
    )
    return {
        "schema": "arm-dashboard-batch-topology",
        "version": 1,
        "target_packages_per_batch": TARGET_PACKAGES_PER_BATCH,
        "over_capacity_batches": [
            item.batch
            for item in topology
            if len(item.packages) > TARGET_PACKAGES_PER_BATCH
        ],
        "external_actions": external_actions,
        "local_actions": local_actions,
        "mutable_external_actions": [
            reference
            for reference in external_actions
            if not _is_immutable_external_action(reference)
        ],
        "batches": [
            {
                "batch": item.batch,
                "workflow_path": item.workflow_path,
                "workflow_name": item.workflow_name,
                "artifact_name": item.artifact_name,
                "external_actions": list(item.external_actions),
                "local_actions": list(item.local_actions),
                "packages": [
                    {
                        "job": package.job,
                        "called_job": package.called_job,
                        "workflow_path": package.workflow_path,
                        "package_slug": package.package_slug,
                    }
                    for package in item.packages
                ],
            }
            for item in topology
        ],
    }


def topology_sha256(topology: Sequence[BatchDefinition]) -> str:
    return hashlib.sha256(
        canonical_json(topology_payload(topology)).encode("ascii")
    ).hexdigest()


def _git_environment(root: Path) -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "HOME": os.environ.get("HOME", str(root)),
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", ""),
    }


def validate_checkout_binding(repository_root: Path, expected_sha: str) -> str:
    root = _real_directory(repository_root, "repository root")
    expected = _sha(expected_sha, "expected_sha")
    environment = _git_environment(root)
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=environment,
        )
        status = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                ".github/workflows",
                ".github/actions",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError("could not verify the exact Git checkout") from exc
    observed = head.stdout.strip()
    if observed != expected:
        raise ContractError("checked-out Git commit does not match expected_sha")
    if len(status.stdout.encode("utf-8")) > 1_048_576 or status.stdout:
        raise ContractError(
            "workflow/action topology has uncommitted or untracked changes"
        )
    return expected


def expected_run_title(
    definition: BatchDefinition, orchestration_id: str, dispatch_nonce: str
) -> str:
    orchestration = _orchestration_id(orchestration_id)
    if not isinstance(dispatch_nonce, str) or not _NONCE_RE.fullmatch(dispatch_nonce):
        raise ContractError(
            "dispatch_nonce must be 64 lowercase hexadecimal characters"
        )
    return f"Arm64 Batch {definition.batch} [{orchestration}] [nonce:{dispatch_nonce}]"


def select_exact_workflow_run(
    pages: object,
    *,
    definition: BatchDefinition,
    repository: str,
    branch: str,
    head_sha: str,
    orchestration_id: str,
    dispatch_nonce: str,
) -> dict[str, Any]:
    responses = _api_pages(pages, "workflow-runs response")
    runs: list[object] = []
    total_count: int | None = None
    for page_number, raw_page in enumerate(responses, start=1):
        page = _mapping(raw_page, f"workflow-runs page {page_number}")
        observed_total = _nonnegative_int(
            page.get("total_count"), "workflow run total_count"
        )
        page_runs = page.get("workflow_runs")
        if not isinstance(page_runs, list):
            raise ContractError("workflow-runs response page is malformed")
        if total_count is None:
            total_count = observed_total
        elif observed_total != total_count:
            raise ContractError("workflow run total_count changed during pagination")
        runs.extend(page_runs)
        if len(runs) > MAX_API_ITEMS:
            raise ContractError("workflow-runs response exceeds the item limit")
    if total_count != len(runs):
        raise ContractError("workflow-runs response is incomplete")
    title = expected_run_title(definition, orchestration_id, dispatch_nonce)
    matching = [
        item
        for item in runs
        if isinstance(item, Mapping) and item.get("display_title") == title
    ]
    if len(matching) != 1:
        raise ContractError("exact workflow run is missing or duplicated")
    return validate_workflow_run_api(
        matching[0],
        definition=definition,
        repository=repository,
        branch=branch,
        head_sha=head_sha,
        orchestration_id=orchestration_id,
        dispatch_nonce=dispatch_nonce,
    )


def validate_workflow_run_api(
    payload: object,
    *,
    definition: BatchDefinition,
    repository: str,
    branch: str,
    head_sha: str,
    orchestration_id: str,
    dispatch_nonce: str,
) -> dict[str, Any]:
    run = _mapping(payload, "workflow run API payload")
    expected = {
        "name": definition.workflow_name,
        "path": definition.workflow_path,
        "display_title": expected_run_title(
            definition, orchestration_id, dispatch_nonce
        ),
        "event": "workflow_dispatch",
        "head_branch": _branch(branch),
        "head_sha": _sha(head_sha, "head_sha"),
        "status": "completed",
    }
    for key, value in expected.items():
        if run.get(key) != value:
            raise ContractError(f"workflow run API payload has unexpected {key}")
    if run.get("conclusion") not in {"success", "failure"}:
        raise ContractError("workflow run API payload has a rejected conclusion")
    run_id = _positive_int(run.get("id"), "workflow run id")
    attempt = _positive_int(run.get("run_attempt"), "workflow run attempt")
    if attempt != 1:
        raise ContractError("workflow reruns are not accepted; dispatch a fresh run")
    repository_payload = _mapping(run.get("repository"), "workflow run repository")
    if repository_payload.get("full_name") != _repository(repository):
        raise ContractError("workflow run belongs to another repository")
    created_at, created = _timestamp(run.get("created_at"), "workflow run created_at")
    updated_at, updated = _timestamp(run.get("updated_at"), "workflow run updated_at")
    if created > updated:
        raise ContractError("workflow run timestamps are out of order")
    return {
        "id": run_id,
        "attempt": 1,
        "workflow_path": definition.workflow_path,
        "workflow_name": definition.workflow_name,
        "display_title": expected_run_title(
            definition, orchestration_id, dispatch_nonce
        ),
        "event": "workflow_dispatch",
        "head_branch": branch,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": run["conclusion"],
        "created_at": created_at,
        "updated_at": updated_at,
    }


def expected_job_name(registration: PackageRegistration) -> str:
    return f"{registration.job} / {registration.called_job}"


def select_exact_jobs(
    pages: object,
    *,
    definition: BatchDefinition,
    repository: str,
    run: Mapping[str, Any],
) -> list[dict[str, Any]]:
    responses = _api_pages(pages, "jobs response")
    jobs: list[object] = []
    total_count: int | None = None
    for page_number, raw_page in enumerate(responses, start=1):
        page = _mapping(raw_page, f"jobs page {page_number}")
        observed_total = _nonnegative_int(page.get("total_count"), "job total_count")
        page_jobs = page.get("jobs")
        if not isinstance(page_jobs, list):
            raise ContractError("jobs response page is malformed")
        if total_count is None:
            total_count = observed_total
        elif observed_total != total_count:
            raise ContractError("job total_count changed during pagination")
        jobs.extend(page_jobs)
        if len(jobs) > MAX_API_ITEMS:
            raise ContractError("jobs response exceeds the item limit")
    if total_count != len(jobs):
        raise ContractError("jobs response is incomplete")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for registration in definition.packages:
        name = expected_job_name(registration)
        matching = [
            item
            for item in jobs
            if isinstance(item, Mapping) and item.get("name") == name
        ]
        if len(matching) != 1:
            raise ContractError(f"exact package job is missing or duplicated: {name}")
        job = validate_job_api(
            matching[0],
            registration=registration,
            repository=repository,
            run=run,
        )
        if job["id"] in seen_ids:
            raise ContractError("jobs response reuses a package job ID")
        seen_ids.add(job["id"])
        normalized.append(job)
    return normalized


def validate_job_api(
    payload: object,
    *,
    registration: PackageRegistration,
    repository: str,
    run: Mapping[str, Any],
) -> dict[str, Any]:
    job = _mapping(payload, f"job API payload for {registration.job}")
    job_id = _positive_int(job.get("id"), "job id")
    job_run_id = _positive_int(job.get("run_id"), "job run_id")
    job_run_attempt = _positive_int(job.get("run_attempt"), "job run_attempt")
    if job_run_id != run["id"] or job_run_attempt != run["attempt"]:
        raise ContractError("package job belongs to another run or attempt")
    name = expected_job_name(registration)
    if job.get("name") != name:
        raise ContractError("package job name does not match topology")
    if job.get("status") != "completed" or job.get("conclusion") not in {
        "success",
        "failure",
    }:
        raise ContractError("package job is not terminal with an accepted conclusion")
    repository = _repository(repository)
    html_url = f"https://github.com/{repository}/actions/runs/{run['id']}/job/{job_id}"
    if job.get("html_url") != html_url:
        raise ContractError("package job URL does not match its API identity")
    started_at, started = _timestamp(job.get("started_at"), "job started_at")
    completed_at, completed = _timestamp(job.get("completed_at"), "job completed_at")
    _, run_created = _timestamp(run["created_at"], "run created_at")
    _, run_updated = _timestamp(run["updated_at"], "run updated_at")
    if started > completed or started < run_created or completed > run_updated:
        raise ContractError("package job timestamps are outside the exact run window")
    return {
        "registration_job": registration.job,
        "workflow_path": registration.workflow_path,
        "package_slug": registration.package_slug,
        "id": job_id,
        "name": name,
        "run_id": run["id"],
        "run_attempt": run["attempt"],
        "status": "completed",
        "conclusion": job["conclusion"],
        "started_at": started_at,
        "completed_at": completed_at,
        "html_url": html_url,
    }


def select_exact_artifact(
    pages: object,
    *,
    definition: BatchDefinition,
    run: Mapping[str, Any],
) -> dict[str, Any]:
    responses = _api_pages(pages, "artifacts response")
    artifacts: list[object] = []
    total_count: int | None = None
    for page_number, raw_page in enumerate(responses, start=1):
        page = _mapping(raw_page, f"artifacts page {page_number}")
        observed_total = _nonnegative_int(
            page.get("total_count"), "artifact total_count"
        )
        page_artifacts = page.get("artifacts")
        if not isinstance(page_artifacts, list):
            raise ContractError("artifacts response page is malformed")
        if total_count is None:
            total_count = observed_total
        elif observed_total != total_count:
            raise ContractError("artifact total_count changed during pagination")
        artifacts.extend(page_artifacts)
        if len(artifacts) > MAX_API_ITEMS:
            raise ContractError("artifacts response exceeds the item limit")
    if total_count != len(artifacts):
        raise ContractError("artifacts response is incomplete")
    matching = [
        item
        for item in artifacts
        if isinstance(item, Mapping) and item.get("name") == definition.artifact_name
    ]
    if len(matching) != 1:
        raise ContractError("exact batch artifact is missing or duplicated")
    artifact = _mapping(matching[0], "artifact API payload")
    artifact_id = _positive_int(artifact.get("id"), "artifact id")
    size = _positive_int(artifact.get("size_in_bytes"), "artifact size_in_bytes")
    if size > MAX_BATCH_BYTES:
        raise ContractError("artifact exceeds the batch size limit")
    digest = artifact.get("digest")
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise ContractError("artifact API digest is not canonical SHA-256")
    if artifact.get("expired") is not False:
        raise ContractError("artifact is expired")
    workflow_run = _mapping(artifact.get("workflow_run"), "artifact workflow run")
    if workflow_run.get("id") != run["id"]:
        raise ContractError("artifact belongs to another workflow run")
    created_at, created = _timestamp(artifact.get("created_at"), "artifact created_at")
    _, run_created = _timestamp(run["created_at"], "run created_at")
    _, run_updated = _timestamp(run["updated_at"], "run updated_at")
    if created < run_created or created > run_updated:
        raise ContractError("artifact timestamp is outside the exact run window")
    return {
        "id": artifact_id,
        "name": definition.artifact_name,
        "size_in_bytes": size,
        "digest": digest,
        "created_at": created_at,
        "expired": False,
        "workflow_run_id": run["id"],
    }


def build_manifest_batch(
    *,
    definition: BatchDefinition,
    dispatch_nonce: str,
    run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    if artifact.get("workflow_run_id") != run.get("id"):
        raise ContractError("manifest artifact does not belong to its run")
    return {
        "batch": definition.batch,
        "workflow_path": definition.workflow_path,
        "workflow_name": definition.workflow_name,
        "artifact_name": definition.artifact_name,
        "dispatch_nonce": dispatch_nonce,
        "run": dict(run),
        "jobs": [dict(job) for job in jobs],
        "artifact": dict(artifact),
    }


def validate_manifest(
    payload: object,
    *,
    topology: Sequence[BatchDefinition],
    expected_repository: str,
    expected_branch: str,
    expected_sha: str,
    expected_orchestration_id: str,
    expected_dispatch_nonces: Sequence[str],
    expected_not_before: str,
    expected_not_after: str,
) -> dict[str, Any]:
    manifest = _mapping(payload, "manifest")
    _exact_keys(manifest, _MANIFEST_KEYS, "manifest")
    if manifest["schema"] != MANIFEST_SCHEMA or manifest["version"] != MANIFEST_VERSION:
        raise ContractError("manifest schema or version is unsupported")
    repository = _repository(manifest["repository"])
    branch = _branch(manifest["branch"])
    head_sha = _sha(manifest["head_sha"], "manifest head_sha")
    topology_digest = manifest["topology_sha256"]
    if (
        not isinstance(topology_digest, str)
        or not _SHA256_RE.fullmatch(topology_digest)
        or topology_digest != topology_sha256(topology)
    ):
        raise ContractError(
            "manifest topology_sha256 does not match reviewed workflows"
        )
    mutable_actions = topology_payload(topology)["mutable_external_actions"]
    if mutable_actions:
        raise ContractError(
            "workflow topology contains mutable external execution references: "
            f"{mutable_actions}"
        )
    orchestration_id = _orchestration_id(manifest["orchestration_id"])
    created_at, created_time = _timestamp(manifest["created_at"], "manifest created_at")
    expected_repository = _repository(expected_repository)
    expected_branch = _branch(expected_branch)
    expected_sha = _sha(expected_sha, "expected_sha")
    expected_orchestration_id = _orchestration_id(expected_orchestration_id)
    _, window_start = _timestamp(expected_not_before, "expected_not_before")
    _, window_end = _timestamp(expected_not_after, "expected_not_after")
    if (
        window_start > window_end
        or (window_end - window_start).total_seconds()
        > MAX_ORCHESTRATION_WINDOW_SECONDS
    ):
        raise ContractError("expected orchestration window is invalid or too broad")
    if not window_start <= created_time <= window_end:
        raise ContractError(
            "manifest creation is outside the expected orchestration window"
        )
    if repository != expected_repository:
        raise ContractError(
            "manifest repository does not match the expected repository"
        )
    if branch != expected_branch:
        raise ContractError("manifest branch does not match the expected branch")
    if head_sha != expected_sha:
        raise ContractError("manifest head_sha does not match the expected SHA")
    if orchestration_id != expected_orchestration_id:
        raise ContractError(
            "manifest orchestration_id does not match the current orchestration"
        )

    if isinstance(expected_dispatch_nonces, (str, bytes)) or len(
        expected_dispatch_nonces
    ) != len(topology):
        raise ContractError("expected dispatch nonce list is incomplete")
    expected_nonces = tuple(
        _nonce(value, f"expected dispatch nonce {index}")
        for index, value in enumerate(expected_dispatch_nonces, start=1)
    )
    if len(set(expected_nonces)) != len(expected_nonces):
        raise ContractError("expected dispatch nonces must be unique")

    raw_batches = manifest["batches"]
    if not isinstance(raw_batches, list) or len(raw_batches) != len(topology):
        raise ContractError("manifest must contain one record for every batch")
    normalized: list[dict[str, Any]] = []
    run_ids: set[int] = set()
    job_ids: set[int] = set()
    artifact_ids: set[int] = set()
    nonces: set[str] = set()
    for definition, raw_record in zip(topology, raw_batches, strict=True):
        record = _validate_manifest_batch(
            raw_record,
            definition=definition,
            repository=repository,
            branch=branch,
            head_sha=head_sha,
            orchestration_id=orchestration_id,
            manifest_time=created_time,
            expected_nonce=expected_nonces[definition.batch - 1],
            window_start=window_start,
            window_end=window_end,
        )
        run_id = record["run"]["id"]
        artifact_id = record["artifact"]["id"]
        nonce = record["dispatch_nonce"]
        if run_id in run_ids or artifact_id in artifact_ids or nonce in nonces:
            raise ContractError(
                "manifest contains duplicate run, artifact, or nonce identity"
            )
        run_ids.add(run_id)
        artifact_ids.add(artifact_id)
        nonces.add(nonce)
        for job in record["jobs"]:
            if job["id"] in job_ids:
                raise ContractError("manifest contains a duplicate package job ID")
            job_ids.add(job["id"])
        normalized.append(record)
    return {
        "schema": MANIFEST_SCHEMA,
        "version": MANIFEST_VERSION,
        "repository": repository,
        "branch": branch,
        "head_sha": head_sha,
        "topology_sha256": topology_digest,
        "orchestration_id": orchestration_id,
        "created_at": created_at,
        "batches": normalized,
    }


def validate_manifest_text(
    raw: bytes,
    *,
    topology: Sequence[BatchDefinition],
    expected_repository: str,
    expected_branch: str,
    expected_sha: str,
    expected_orchestration_id: str,
    expected_dispatch_nonces: Sequence[str],
    expected_not_before: str,
    expected_not_after: str,
) -> dict[str, Any]:
    payload, text = _json_bytes(raw, "manifest", MAX_MANIFEST_BYTES)
    manifest = validate_manifest(
        payload,
        topology=topology,
        expected_repository=expected_repository,
        expected_branch=expected_branch,
        expected_sha=expected_sha,
        expected_orchestration_id=expected_orchestration_id,
        expected_dispatch_nonces=expected_dispatch_nonces,
        expected_not_before=expected_not_before,
        expected_not_after=expected_not_after,
    )
    if text != canonical_json(manifest) + "\n":
        raise ContractError(
            "manifest must be canonical compact JSON with one trailing newline"
        )
    return manifest


def validate_batch_artifact(
    *,
    artifact_archive: Path,
    manifest: Mapping[str, Any],
    topology: Sequence[BatchDefinition],
    batch: int,
) -> dict[str, Any]:
    batch_number = _positive_int(batch, "batch")
    if batch_number > len(topology):
        raise ContractError("batch is outside the discovered topology")
    record = _mapping(manifest["batches"][batch_number - 1], "manifest batch")
    archive_parent = _real_directory(artifact_archive.parent, "artifact archive parent")
    archive_raw = _read_regular_file(
        artifact_archive,
        root=archive_parent,
        label="artifact archive",
        maximum_bytes=MAX_BATCH_BYTES,
    )
    if len(archive_raw) != record["artifact"]["size_in_bytes"]:
        raise ContractError("artifact archive size does not match API identity")
    archive_digest = "sha256:" + hashlib.sha256(archive_raw).hexdigest()
    if archive_digest != record["artifact"]["digest"]:
        raise ContractError("artifact archive digest does not match API identity")
    with tempfile.TemporaryDirectory(prefix="arm-dashboard-exact-run-") as temporary:
        root = Path(temporary) / "artifact"
        root.mkdir(mode=0o700)
        _extract_verified_archive(archive_raw, root)
        return _validate_extracted_batch(
            root,
            manifest=manifest,
            topology=topology,
            batch=batch_number,
            archive_digest=archive_digest,
        )


def _validate_extracted_batch(
    artifact_root: Path,
    *,
    manifest: Mapping[str, Any],
    topology: Sequence[BatchDefinition],
    batch: int,
    archive_digest: str,
) -> dict[str, Any]:
    batch_number = _positive_int(batch, "batch")
    if batch_number > len(topology):
        raise ContractError("batch is outside the discovered topology")
    definition = topology[batch_number - 1]
    record = _mapping(manifest["batches"][batch_number - 1], "manifest batch")
    root = _real_directory(artifact_root, "artifact root")
    inventory, directories = _inventory(root)
    sentinel_relative = Path(BATCH_ATTESTATION_NAME)
    if sentinel_relative not in inventory:
        raise ContractError("batch artifact is missing its attestation sentinel")
    sentinel_path = root / sentinel_relative
    sentinel_raw = _read_regular_file(
        sentinel_path,
        root=root,
        label="batch attestation",
        maximum_bytes=MAX_BATCH_ATTESTATION_BYTES,
    )
    sentinel_payload, sentinel_text = _json_bytes(
        sentinel_raw, "batch attestation", MAX_BATCH_ATTESTATION_BYTES
    )
    attestation = _mapping(sentinel_payload, "batch attestation")
    _exact_keys(attestation, _BATCH_ATTESTATION_KEYS, "batch attestation")
    if (
        attestation["schema"] != BATCH_ATTESTATION_SCHEMA
        or attestation["version"] != BATCH_ATTESTATION_VERSION
    ):
        raise ContractError("batch attestation schema or version is unsupported")
    expected_scalars = {
        "repository": manifest["repository"],
        "orchestration_id": manifest["orchestration_id"],
        "batch": batch_number,
        "workflow_path": definition.workflow_path,
        "artifact_name": definition.artifact_name,
        "dispatch_nonce": record["dispatch_nonce"],
        "branch": manifest["branch"],
        "head_sha": manifest["head_sha"],
        "run_id": record["run"]["id"],
        "run_attempt": record["run"]["attempt"],
    }
    for key, expected in expected_scalars.items():
        if attestation[key] != expected:
            raise ContractError(f"batch attestation has unexpected {key}")
    collector = _mapping(attestation["collector"], "collector proof")
    _exact_keys(collector, _COLLECTOR_KEYS, "collector proof")
    if collector["status"] != "success":
        raise ContractError("collector did not attest successful result assembly")
    if collector["result_count"] != len(definition.packages):
        raise ContractError("collector result count does not match batch registration")
    packages = attestation["packages"]
    if not isinstance(packages, list) or len(packages) != len(definition.packages):
        raise ContractError("batch attestation package list is incomplete")

    expected_files = {sentinel_relative}
    normalized_packages: list[dict[str, Any]] = []
    package_outcomes: list[dict[str, Any]] = []
    for registration, job, raw_package in zip(
        definition.packages, record["jobs"], packages, strict=True
    ):
        package = _mapping(raw_package, "attested package")
        _exact_keys(package, _ATTESTED_PACKAGE_KEYS, "attested package")
        slug = _slug(package["package_slug"], "attested package_slug")
        if slug != registration.package_slug:
            raise ContractError("attested package_slug does not match registration")
        expected_path = Path(f"{registration.package_slug}-test-results") / (
            f"{registration.package_slug}.json"
        )
        expected = {
            "job": registration.job,
            "workflow_path": registration.workflow_path,
            "package_slug": registration.package_slug,
            "result_path": expected_path.as_posix(),
        }
        for key, value in expected.items():
            if package[key] != value:
                raise ContractError(f"attested package has unexpected {key}")
        result_path = root / expected_path
        result_raw = _read_regular_file(
            result_path,
            root=root,
            label=f"result for {slug}",
            maximum_bytes=MAX_RESULT_BYTES,
        )
        digest = hashlib.sha256(result_raw).hexdigest()
        if package["sha256"] != digest or not _SHA256_RE.fullmatch(
            str(package["sha256"])
        ):
            raise ContractError(f"result digest does not match for {slug}")
        result_payload, _ = _json_bytes(
            result_raw, f"result for {slug}", MAX_RESULT_BYTES
        )
        normalized_result = validate_package_result(
            result_payload,
            registration=registration,
            repository=manifest["repository"],
            batch=batch_number,
            run=record["run"],
            job=job,
        )
        expected_files.add(expected_path)
        normalized_packages.append({**expected, "sha256": digest})
        package_outcomes.append(
            {
                **expected,
                "sha256": digest,
                "job_id": job["id"],
                "job_name": job["name"],
                "job_url": job["html_url"],
                "run_status": normalized_result["run"]["status"],
                "badge_status": normalized_result["metadata"]["badge_status"],
            }
        )
    expected_directories = {
        path.parent for path in expected_files if path.parent != Path(".")
    }
    if set(inventory) != expected_files or directories != expected_directories:
        missing = sorted(str(path) for path in expected_files - set(inventory))
        extra = sorted(str(path) for path in set(inventory) - expected_files)
        raise ContractError(
            "batch artifact has missing or unexpected paths: "
            f"missing={missing}, extra={extra}, "
            f"directories={sorted(str(path) for path in directories)}"
        )

    normalized_attestation = {
        "schema": BATCH_ATTESTATION_SCHEMA,
        "version": BATCH_ATTESTATION_VERSION,
        **expected_scalars,
        "collector": {"status": "success", "result_count": len(normalized_packages)},
        "packages": normalized_packages,
    }
    if sentinel_text != canonical_json(normalized_attestation) + "\n":
        raise ContractError("batch attestation must be canonical compact JSON")
    expected_conclusion = (
        "failure"
        if any(item["run_status"] == "failure" for item in package_outcomes)
        else "success"
    )
    if record["run"]["conclusion"] != expected_conclusion:
        raise ContractError(
            "batch conclusion contradicts its complete package evidence"
        )
    return {
        "batch": batch_number,
        "run_id": record["run"]["id"],
        "run_attempt": record["run"]["attempt"],
        "artifact_id": record["artifact"]["id"],
        "artifact_digest": record["artifact"]["digest"],
        "attestation_sha256": hashlib.sha256(sentinel_raw).hexdigest(),
        "archive_sha256": archive_digest.removeprefix("sha256:"),
        "packages": package_outcomes,
    }


def validate_package_result(
    payload: object,
    *,
    registration: PackageRegistration,
    repository: str,
    batch: int,
    run: Mapping[str, Any],
    job: Mapping[str, Any],
) -> dict[str, Any]:
    result = _mapping(payload, f"result for {registration.package_slug}")
    _exact_keys(result, _RESULT_KEYS, "package result")
    if result["schema_version"] != "2.0":
        raise ContractError("package result schema_version is unsupported")
    package = _mapping(result["package"], "package")
    _exact_keys(package, _PACKAGE_KEYS, "package")
    name = _bounded_text(package["name"], "package name", 200)
    version = _bounded_text(package["version"], "package version", 200)
    if version.strip().lower() in {"unknown", "n/a", "na", "none", "null"}:
        raise ContractError("package version must not be a placeholder")

    result_run = _mapping(result["run"], "package run")
    _exact_keys(result_run, _RESULT_RUN_KEYS, "package run")
    if result_run["id"] != str(run["id"]) or result_run["attempt"] != str(
        run["attempt"]
    ):
        raise ContractError("package result belongs to another run or attempt")
    result_status = result_run["status"]
    if result_status not in {"success", "failure"}:
        raise ContractError("package result has an invalid run status")
    runner = _mapping(result_run["runner"], "runner")
    _exact_keys(runner, _RUNNER_KEYS, "runner")
    if runner != {"os": "ubuntu-24.04", "arch": "arm64"}:
        raise ContractError("package result is not native ubuntu-24.04 Arm64 evidence")
    url_match = _RUN_URL_RE.fullmatch(str(result_run["url"]))
    if (
        url_match is None
        or url_match.group("repository") != repository
        or int(url_match.group("run_id")) != run["id"]
        or int(url_match.group("job_id")) != job["id"]
        or result_run["url"] != job["html_url"]
    ):
        raise ContractError("package result URL is not an exact job URL for this run")
    result_job_id = url_match.group("job_id")
    if result_run["job_name"] != job["name"]:
        raise ContractError("package result job_name does not match registration")
    timestamp, timestamp_value = _timestamp(
        result_run["timestamp"], "package timestamp"
    )
    _, run_created = _timestamp(run["created_at"], "run created_at")
    _, run_updated = _timestamp(run["updated_at"], "run updated_at")
    _, job_started = _timestamp(job["started_at"], "job started_at")
    _, job_completed = _timestamp(job["completed_at"], "job completed_at")
    if (
        timestamp_value < run_created
        or timestamp_value > run_updated
        or timestamp_value < job_started
        or timestamp_value > job_completed
    ):
        raise ContractError("package timestamp is outside the exact job window")

    tests = _mapping(result["tests"], "tests")
    _exact_keys(tests, _TEST_KEYS, "tests")
    passed = _nonnegative_int(tests["passed"], "tests.passed")
    failed = _nonnegative_int(tests["failed"], "tests.failed")
    skipped = _nonnegative_int(tests["skipped"], "tests.skipped")
    duration = _nonnegative_int(tests["duration_seconds"], "tests.duration_seconds")
    details = _validate_test_details(tests["details"])
    actual_counts = {
        "passed": sum(item["status"] == "passed" for item in details),
        "failed": sum(item["status"] == "failed" for item in details),
        "skipped": sum(item["status"] == "skipped" for item in details),
    }
    if actual_counts != {"passed": passed, "failed": failed, "skipped": skipped}:
        raise ContractError("package test counters do not match six detail records")
    for index, detail in enumerate(details, start=1):
        detail_url = _RUN_URL_RE.fullmatch(detail["url"])
        if (
            detail_url is None
            or detail_url.group("repository") != repository
            or int(detail_url.group("run_id")) != run["id"]
            or detail_url.group("job_id") != result_job_id
        ):
            raise ContractError(
                f"test detail {index} URL is not bound to the exact package job"
            )

    metadata = _mapping(result["metadata"], "metadata")
    _exact_keys(metadata, _METADATA_KEYS, "metadata")
    slug = _slug(metadata["package_slug"], "metadata.package_slug")
    if slug != registration.package_slug:
        raise ContractError("package result slug does not match workflow registration")
    if metadata["dashboard_link"] != f"/linux/opensource_packages/{slug}":
        raise ContractError("dashboard_link is not the canonical package route")
    if metadata["contract_version"] != "2.0":
        raise ContractError("package result contract_version is unsupported")
    if metadata["batch_title"] != f"Batch {batch}":
        raise ContractError("package result batch_title is incorrect")
    if metadata["job_url_resolution_status"] != "central_exact":
        raise ContractError("package result did not resolve an exact job URL")
    badge_status = metadata["badge_status"]
    if badge_status not in {"passing", "failing"}:
        raise ContractError("package result has an invalid badge_status")
    core_failed = _nonnegative_int(metadata["core_failed"], "metadata.core_failed")
    baseline_failed = sum(item["status"] == "failed" for item in details[:5])
    if core_failed != baseline_failed:
        raise ContractError("core_failed must equal failed baseline tests 1-5")
    regression_status = metadata["regression_status"]
    if regression_status not in _REGRESSION_STATUSES:
        raise ContractError("package result has an invalid regression_status")
    regression_decision = _decision(metadata["regression_decision"])
    regression_applicability = _decision(
        metadata["regression_applicability"], label="regression_applicability"
    )
    regression_reason = _decision(
        metadata["regression_reason"], label="regression_reason"
    )
    regression_note = _bounded_text(
        metadata["regression_note"], "regression_note", MAX_DETAIL_TEXT
    )
    if len(regression_note.strip()) < 20:
        raise ContractError(
            "regression_note must meaningfully explain the Test 6 result"
        )
    regression_detail_status = details[5]["status"]
    if details[5]["decision"] != regression_decision:
        raise ContractError("Test 6 detail decision contradicts regression metadata")
    if details[5].get("current_version", version) != version:
        raise ContractError("Test 6 current_version contradicts package version")
    if details[5].get("regression_result", regression_status) != regression_status:
        raise ContractError("Test 6 regression_result contradicts regression metadata")
    expected_regression_detail = {
        "passed": "passed",
        "failed": "failed",
        "skipped": "skipped",
        "deferred": "skipped",
        "not_applicable": "skipped",
    }[regression_status]
    if regression_detail_status != expected_regression_detail:
        raise ContractError("regression metadata does not match Test 6 detail status")

    if baseline_failed:
        expected_success = False
        if (
            regression_status != "skipped"
            or regression_decision not in _BASELINE_REGRESSION_DECISIONS
            or regression_applicability != "not_applicable"
            or regression_reason != regression_decision
        ):
            raise ContractError(
                "baseline failure must emit an explicit baseline decision"
            )
    elif regression_status == "failed":
        if (
            regression_decision not in _FAILED_REGRESSION_DECISIONS
            or regression_applicability != "applicable"
            or regression_reason != regression_decision
        ):
            raise ContractError("failed Test 6 has contradictory regression metadata")
        expected_success = False
    elif regression_status == "deferred":
        if (
            regression_decision not in _DEFERRED_REGRESSION_DECISIONS
            or regression_applicability != "applicable"
            or regression_reason != regression_decision
        ):
            raise ContractError(
                "deferred Test 6 requires an approved explicit decision"
            )
        expected_success = True
    elif regression_status == "not_applicable":
        if (
            regression_decision not in _NOT_APPLICABLE_REGRESSION_DECISIONS
            or regression_applicability != "not_applicable"
            or regression_reason != regression_decision
        ):
            raise ContractError(
                "not-applicable Test 6 requires an approved explicit decision"
            )
        expected_success = True
    elif regression_status == "skipped":
        raise ContractError(
            "Test 6 skipped is reserved for an explicit baseline failure"
        )
    else:
        if (
            regression_decision not in _PASSED_REGRESSION_DECISIONS
            or regression_applicability != "applicable"
            or regression_reason != "validated"
        ):
            raise ContractError("passed Test 6 has contradictory regression metadata")
        expected_success = True
    expected_status = "success" if expected_success else "failure"
    expected_badge = "passing" if expected_success else "failing"
    if (
        result_status != expected_status
        or badge_status != expected_badge
        or job["conclusion"] != expected_status
    ):
        raise ContractError(
            "job conclusion, run_status, or badge_status contradicts strict six-test policy"
        )
    return {
        "schema_version": "2.0",
        "package": {"name": name, "version": version},
        "run": {
            "id": str(run["id"]),
            "attempt": str(run["attempt"]),
            "url": result_run["url"],
            "timestamp": timestamp,
            "status": expected_status,
            "runner": {"os": "ubuntu-24.04", "arch": "arm64"},
            "job_name": job["name"],
        },
        "tests": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration_seconds": duration,
            "details": details,
        },
        "metadata": dict(metadata),
    }


def build_aggregate_attestation(
    *,
    manifest: Mapping[str, Any],
    topology: Sequence[BatchDefinition],
    artifact_archives: Sequence[Path],
) -> dict[str, Any]:
    if len(artifact_archives) != len(manifest["batches"]) or len(topology) != len(
        manifest["batches"]
    ):
        raise ContractError("aggregate input must contain every manifest artifact")
    normalized: list[dict[str, Any]] = []
    overall_status = "success"
    for expected_batch, (definition, archive) in enumerate(
        zip(topology, artifact_archives, strict=True), start=1
    ):
        raw = validate_batch_artifact(
            artifact_archive=archive,
            manifest=manifest,
            topology=topology,
            batch=expected_batch,
        )
        proof = _mapping(raw, f"batch proof {expected_batch}")
        _exact_keys(proof, _BATCH_PROOF_KEYS, f"batch proof {expected_batch}")
        if proof.get("batch") != expected_batch:
            raise ContractError(
                "aggregate batch proofs are missing, extra, or reordered"
            )
        record = _mapping(manifest["batches"][expected_batch - 1], "manifest batch")
        expected_identity = {
            "run_id": record["run"]["id"],
            "run_attempt": record["run"]["attempt"],
            "artifact_id": record["artifact"]["id"],
            "artifact_digest": record["artifact"]["digest"],
            "archive_sha256": record["artifact"]["digest"].removeprefix("sha256:"),
        }
        for key, expected in expected_identity.items():
            if proof[key] != expected:
                raise ContractError(
                    f"batch proof {expected_batch} has unexpected {key}"
                )
        attestation_digest = proof["attestation_sha256"]
        if not isinstance(attestation_digest, str) or not _SHA256_RE.fullmatch(
            attestation_digest
        ):
            raise ContractError("batch proof has invalid attestation_sha256")
        raw_packages = proof["packages"]
        if not isinstance(raw_packages, list) or len(raw_packages) != len(
            definition.packages
        ):
            raise ContractError("batch proof package list is incomplete")
        packages: list[dict[str, Any]] = []
        for registration, job, raw_package in zip(
            definition.packages, record["jobs"], raw_packages, strict=True
        ):
            package = _mapping(raw_package, "aggregate package proof")
            _exact_keys(
                package,
                _AGGREGATE_PACKAGE_PROOF_KEYS,
                "aggregate package proof",
            )
            expected_path = (
                f"{registration.package_slug}-test-results/"
                f"{registration.package_slug}.json"
            )
            expected_package = {
                "job": registration.job,
                "workflow_path": registration.workflow_path,
                "package_slug": registration.package_slug,
                "result_path": expected_path,
                "job_id": job["id"],
                "job_name": job["name"],
                "job_url": job["html_url"],
            }
            for key, expected in expected_package.items():
                if package[key] != expected:
                    raise ContractError(f"aggregate package proof has unexpected {key}")
            digest = package["sha256"]
            if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
                raise ContractError("aggregate package proof has invalid SHA-256")
            status = package["run_status"]
            badge = package["badge_status"]
            if (status, badge) not in {
                ("success", "passing"),
                ("failure", "failing"),
            }:
                raise ContractError("aggregate package status and badge contradict")
            if status == "failure":
                overall_status = "failure"
            packages.append(
                {
                    **expected_package,
                    "sha256": digest,
                    "run_status": status,
                    "badge_status": badge,
                }
            )
        normalized.append(
            {
                "batch": expected_batch,
                **expected_identity,
                "attestation_sha256": attestation_digest,
                "packages": packages,
            }
        )
    return {
        "schema": AGGREGATE_ATTESTATION_SCHEMA,
        "version": AGGREGATE_ATTESTATION_VERSION,
        "repository": manifest["repository"],
        "branch": manifest["branch"],
        "head_sha": manifest["head_sha"],
        "topology_sha256": manifest["topology_sha256"],
        "orchestration_id": manifest["orchestration_id"],
        "created_at": manifest["created_at"],
        "overall_status": overall_status,
        "manifest_sha256": hashlib.sha256(
            (canonical_json(manifest) + "\n").encode("ascii")
        ).hexdigest(),
        "batches": normalized,
    }


def _validate_manifest_batch(
    payload: object,
    *,
    definition: BatchDefinition,
    repository: str,
    branch: str,
    head_sha: str,
    orchestration_id: str,
    manifest_time: datetime,
    expected_nonce: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    record = _mapping(payload, f"batch {definition.batch} record")
    _exact_keys(record, _MANIFEST_BATCH_KEYS, f"batch {definition.batch} record")
    expected = {
        "batch": definition.batch,
        "workflow_path": definition.workflow_path,
        "workflow_name": definition.workflow_name,
        "artifact_name": definition.artifact_name,
    }
    for key, value in expected.items():
        if record[key] != value:
            raise ContractError(f"batch {definition.batch} record has unexpected {key}")
    nonce = _nonce(record["dispatch_nonce"], "dispatch_nonce")
    if nonce != expected_nonce:
        raise ContractError("dispatch_nonce does not match the current launch plan")
    run = _mapping(record["run"], f"batch {definition.batch} run")
    _exact_keys(run, _RUN_KEYS, f"batch {definition.batch} run")
    run_id = _positive_int(run["id"], "run id")
    attempt = _positive_int(run["attempt"], "run attempt")
    if attempt != 1:
        raise ContractError(
            "run attempt must be 1; retries require a fresh dispatch and nonce"
        )
    expected_run_identity = {
        "workflow_path": definition.workflow_path,
        "workflow_name": definition.workflow_name,
        "display_title": expected_run_title(definition, orchestration_id, nonce),
    }
    for key, value in expected_run_identity.items():
        if run[key] != value:
            raise ContractError(f"batch run has unexpected {key}")
    if run["event"] != "workflow_dispatch":
        raise ContractError("batch run event must be workflow_dispatch")
    if run["head_branch"] != branch or run["head_sha"] != head_sha:
        raise ContractError("batch run branch or SHA does not match manifest")
    if run["status"] != "completed" or run["conclusion"] not in {"success", "failure"}:
        raise ContractError("batch run is not terminal with an accepted conclusion")
    run_created_at, run_created = _timestamp(run["created_at"], "run created_at")
    run_updated_at, run_updated = _timestamp(run["updated_at"], "run updated_at")
    if (
        run_created > run_updated
        or run_updated > manifest_time
        or run_created < window_start
        or run_updated > window_end
    ):
        raise ContractError(
            "batch run timestamps are not ordered within the manifest window"
        )
    jobs = _validate_manifest_jobs(
        record["jobs"],
        definition=definition,
        repository=repository,
        run=run,
    )

    artifact = _mapping(record["artifact"], f"batch {definition.batch} artifact")
    _exact_keys(artifact, _ARTIFACT_KEYS, f"batch {definition.batch} artifact")
    artifact_id = _positive_int(artifact["id"], "artifact id")
    if artifact["name"] != definition.artifact_name:
        raise ContractError("artifact name does not match batch topology")
    size = _positive_int(artifact["size_in_bytes"], "artifact size_in_bytes")
    if size > MAX_BATCH_BYTES:
        raise ContractError("artifact exceeds the batch size limit")
    digest = artifact["digest"]
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise ContractError("artifact digest is not a canonical SHA-256 digest")
    artifact_created_at, artifact_created = _timestamp(
        artifact["created_at"], "artifact created_at"
    )
    if artifact_created < run_created or artifact_created > run_updated:
        raise ContractError("artifact timestamp is outside the exact run window")
    if artifact["expired"] is not False:
        raise ContractError("artifact is expired")
    if artifact["workflow_run_id"] != run_id:
        raise ContractError("artifact belongs to another workflow run")
    return {
        **expected,
        "dispatch_nonce": nonce,
        "run": {
            "id": run_id,
            "attempt": attempt,
            **expected_run_identity,
            "event": "workflow_dispatch",
            "head_branch": branch,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": run["conclusion"],
            "created_at": run_created_at,
            "updated_at": run_updated_at,
        },
        "jobs": jobs,
        "artifact": {
            "id": artifact_id,
            "name": definition.artifact_name,
            "size_in_bytes": size,
            "digest": digest,
            "created_at": artifact_created_at,
            "expired": False,
            "workflow_run_id": run_id,
        },
    }


def _validate_manifest_jobs(
    payload: object,
    *,
    definition: BatchDefinition,
    repository: str,
    run: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or len(payload) != len(definition.packages):
        raise ContractError("manifest must contain one API job for every package")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for registration, raw_job in zip(definition.packages, payload, strict=True):
        job = _mapping(raw_job, f"manifest job for {registration.job}")
        _exact_keys(job, _JOB_KEYS, f"manifest job for {registration.job}")
        expected = validate_job_api(
            job,
            registration=registration,
            repository=repository,
            run=run,
        )
        if dict(job) != expected:
            raise ContractError("manifest package job is not canonical API evidence")
        if expected["id"] in seen_ids:
            raise ContractError("manifest batch contains a duplicate package job ID")
        seen_ids.add(expected["id"])
        normalized.append(expected)
    return normalized


def _shell_step_writes_github_output(
    step: Mapping[str, Any], output: str
) -> bool:
    run = step.get("run")
    if not isinstance(run, str):
        return False
    executable_lines = [
        raw_line
        for raw_line in run.splitlines()
        if raw_line.strip() and not raw_line.lstrip().startswith("#")
    ]
    if len(executable_lines) != 1:
        return False
    lexer = shlex.shlex(
        executable_lines[0],
        posix=True,
        punctuation_chars=";&|<>()",
    )
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise ContractError("strict action contains malformed shell") from exc
    if tokens.count(">>") != 1:
        return False
    redirect = tokens.index(">>")
    if (
        redirect + 2 != len(tokens)
        or tokens[redirect + 1]
        not in {"$GITHUB_OUTPUT", "${GITHUB_OUTPUT}"}
    ):
        return False
    command = tokens[:redirect]
    prefix = f"{output}="
    return (
        len(command) == 2
        and command[0] == "echo"
        and command[1].startswith(prefix)
        and command[1] != prefix
    )


def _validate_strict_batch_action_contract(root: Path) -> None:
    reference = "./.github/actions/collect-batch-observations"
    parts = PurePosixPath(reference.removeprefix("./")).parts
    action_root = _real_directory(root.joinpath(*parts), f"local action {reference}")
    candidates = [
        candidate
        for candidate in (action_root / "action.yml", action_root / "action.yaml")
        if candidate.exists()
    ]
    if len(candidates) != 1:
        raise ContractError(
            "strict batch action must contain exactly one action manifest"
        )
    raw = _read_regular_file(
        candidates[0],
        root=root,
        label="strict batch action manifest",
        maximum_bytes=MAX_WORKFLOW_FILE_BYTES,
    )
    action = _yaml_mapping(raw, "strict batch action manifest")
    expected_inputs = {
        "batch_number",
        "orchestration_id",
        "dispatch_nonce",
        "package_observations_json",
    }
    inputs = _mapping(action.get("inputs"), "strict batch action inputs")
    if set(inputs) != expected_inputs:
        raise ContractError("strict batch action inputs are not exact")
    for name in sorted(expected_inputs):
        declaration = _mapping(
            inputs.get(name), f"strict batch action input {name}"
        )
        if declaration.get("required") is not True or "default" in declaration:
            raise ContractError(
                f"strict batch action input {name} must be required without a default"
            )

    outputs = _mapping(action.get("outputs"), "strict batch action outputs")
    if set(outputs) != {"artifact_path"}:
        raise ContractError("strict batch action outputs are not exact")
    declaration = _mapping(
        outputs.get("artifact_path"), "strict batch action artifact_path output"
    )
    value = declaration.get("value")
    match = (
        _ACTION_OUTPUT_VALUE_RE.fullmatch(value)
        if isinstance(value, str)
        else None
    )
    if match is None or match.group("output") != "artifact_path":
        raise ContractError("strict batch action artifact_path binding is invalid")

    runs = _mapping(action.get("runs"), "strict batch action runs")
    steps = runs.get("steps")
    if runs.get("using") != "composite" or not isinstance(steps, list):
        raise ContractError("strict batch action must be composite")
    source_steps = [
        step
        for step in steps
        if isinstance(step, Mapping) and step.get("id") == match.group("step")
    ]
    source_step = source_steps[0] if len(source_steps) == 1 else None
    if (
        source_step is None
        or source_step.get("shell") != "bash"
        or source_step.get("if") is not None
        or source_step.get("continue-on-error") not in {None, False}
        or not _shell_step_writes_github_output(source_step, "artifact_path")
    ):
        raise ContractError(
            "strict batch action artifact_path output is not produced"
        )


def _parse_batch_workflow(path: Path, *, batch: int, root: Path) -> BatchDefinition:
    raw = _read_regular_file(
        path,
        root=root,
        label=f"batch {batch} workflow",
        maximum_bytes=2_097_152,
    )
    workflow = _yaml_mapping(raw, f"batch {batch} workflow")
    batch_external, batch_local = _collect_reachable_action_references(
        workflow, f"batch {batch} workflow", root=root
    )
    external_actions = set(batch_external)
    local_actions = set(batch_local)
    workflow_name = f"Test All Packages (Batch {batch}) on Arm64"
    if workflow.get("name") != workflow_name:
        raise ContractError(f"batch {batch} workflow name is not canonical")
    jobs = _mapping(workflow.get("jobs"), f"batch {batch} jobs")
    summary = _mapping(jobs.get("summary"), f"batch {batch} summary")
    package_jobs = [
        (str(job), definition) for job, definition in jobs.items() if job != "summary"
    ]
    if not package_jobs or len(package_jobs) > MAX_PACKAGES_PER_BATCH:
        raise ContractError(f"batch {batch} has an invalid package count")
    registrations: list[PackageRegistration] = []
    for job, raw_definition in package_jobs:
        job_definition = _mapping(raw_definition, f"batch {batch} job {job}")
        uses_value = job_definition.get("uses")
        prefix = "./.github/workflows/"
        if (
            not _JOB_RE.fullmatch(job)
            or not isinstance(uses_value, str)
            or not uses_value.startswith(prefix)
        ):
            raise ContractError(f"batch {batch} has malformed package job {job!r}")
        called_name = uses_value.removeprefix(prefix)
        if not _WORKFLOW_FILE_RE.fullmatch(called_name):
            raise ContractError(f"batch {batch} has malformed called workflow")
        called_path = f".github/workflows/{called_name}"
        called_file = root / called_path
        called_raw = _read_regular_file(
            called_file,
            root=root,
            label=f"called workflow for {job}",
            maximum_bytes=2_097_152,
        )
        called_workflow = _yaml_mapping(called_raw, f"called workflow for {job}")
        called_external, called_local = _collect_reachable_action_references(
            called_workflow,
            f"called workflow for {job}",
            root=root,
        )
        external_actions.update(called_external)
        local_actions.update(called_local)
        called_jobs = _mapping(called_workflow.get("jobs"), f"called jobs for {job}")
        if len(called_jobs) != 1:
            raise ContractError(
                f"called workflow for {job} must have exactly one native Arm64 job"
            )
        called_job_name, raw_called_job = next(iter(called_jobs.items()))
        if not isinstance(called_job_name, str) or not _CALLED_JOB_RE.fullmatch(
            called_job_name
        ):
            raise ContractError(f"called workflow for {job} has a malformed job ID")
        called_job = _mapping(raw_called_job, f"called workflow job for {job}")
        if called_job.get("runs-on") != "ubuntu-24.04-arm":
            raise ContractError(
                f"called workflow for {job} must run on ubuntu-24.04-arm"
            )
        slug = _slug(Path(called_name).stem.removeprefix("test-"), f"slug for {job}")
        registrations.append(
            PackageRegistration(job, called_job_name, called_path, slug)
        )
    expected_needs = [item.job for item in registrations]
    observed_needs = summary.get("needs")
    if not isinstance(observed_needs, list) or observed_needs != expected_needs:
        raise ContractError(f"batch {batch} summary needs list is not canonical")
    artifact_name = f"batch{batch}-test-results"
    if summary.get("runs-on") != "ubuntu-24.04-arm" or summary.get("if") != "always()":
        raise ContractError(f"batch {batch} summary runner or condition is incorrect")
    steps = summary.get("steps")
    if not isinstance(steps, list):
        raise ContractError(f"batch {batch} summary steps are malformed")
    collector_references = {
        "./.github/actions/collect-batch-results",
        "./.github/actions/collect-batch-observations",
    }
    legacy_collectors = [
        step
        for step in steps
        if isinstance(step, Mapping)
        and step.get("uses") == "./.github/actions/collect-batch-results"
    ]
    strict_collectors = [
        step
        for step in steps
        if isinstance(step, Mapping)
        and step.get("uses") == "./.github/actions/collect-batch-observations"
    ]
    uploaders = [
        step
        for step in steps
        if isinstance(step, Mapping)
        and isinstance(step.get("uses"), str)
        and str(step["uses"]).startswith("actions/upload-artifact@")
    ]
    if len(legacy_collectors) + len(strict_collectors) != 1 or len(uploaders) != 1:
        raise ContractError(
            f"batch {batch} summary collector/upload contract is incomplete"
        )
    direct_collector = (
        legacy_collectors[0] if legacy_collectors else strict_collectors[0]
    )
    direct_reference = str(direct_collector["uses"])
    action_cache: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    _, collector_graph = _resolve_local_action_references(
        direct_reference,
        root=root,
        cache=action_cache,
        active=set(),
    )
    if set(collector_graph).intersection(collector_references) != {
        direct_reference
    }:
        raise ContractError(
            f"batch {batch} collector action contains another collector"
        )
    for step in steps:
        if step is direct_collector or not isinstance(step, Mapping):
            continue
        reference = step.get("uses")
        if not isinstance(reference, str) or not reference.startswith(
            "./.github/actions/"
        ):
            continue
        _, reachable = _resolve_local_action_references(
            reference,
            root=root,
            cache=action_cache,
            active=set(),
        )
        if set(reachable).intersection(collector_references):
            raise ContractError(
                f"batch {batch} summary contains a nested collector conflict"
            )

    uploader = uploaders[0]
    if (
        steps.index(uploader) <= steps.index(direct_collector)
        or uploader.get("if")
        not in {None, "always()", "${{ always() }}"}
        or uploader.get("continue-on-error") not in {None, False}
        or direct_collector.get("continue-on-error") not in {None, False}
    ):
        raise ContractError(
            f"batch {batch} collector/upload execution order is unsafe"
        )
    uploader_inputs = _mapping(uploader.get("with"), "uploader inputs")
    if legacy_collectors:
        collector_inputs = _mapping(
            legacy_collectors[0].get("with"), "collector inputs"
        )
        if (
            str(collector_inputs.get("batch_number")) != str(batch)
            or collector_inputs.get("batch_title") != f"Batch {batch}"
            or uploader_inputs.get("name") != artifact_name
            or uploader_inputs.get("path") != "test-results"
        ):
            raise ContractError(
                f"batch {batch} legacy collector/upload inputs are incorrect"
            )
    else:
        strict_collector = strict_collectors[0]
        collector_inputs = _mapping(
            strict_collector.get("with"), "strict collector inputs"
        )
        expected_inputs = {
            "batch_number": str(batch),
            "orchestration_id": "${{ inputs.orchestration_id }}",
            "dispatch_nonce": "${{ inputs.dispatch_nonce }}",
            "package_observations_json": "${{ toJson(needs) }}",
        }
        if (
            strict_collector.get("id") != "collect"
            or strict_collector.get("if")
            not in {None, "always()", "${{ always() }}"}
            or dict(collector_inputs) != expected_inputs
            or uploader_inputs.get("name") != artifact_name
            or uploader_inputs.get("path")
            != "${{ steps.collect.outputs.artifact_path }}"
        ):
            raise ContractError(
                f"batch {batch} strict collector/upload inputs are incorrect"
            )
        _validate_strict_batch_action_contract(root)
        triggers = _mapping(workflow.get("on"), f"batch {batch} triggers")
        expected_triggers = {"workflow_call", "workflow_dispatch"}
        if set(triggers) != expected_triggers:
            raise ContractError(
                f"batch {batch} strict trigger set is not exact"
            )
        identity_inputs = {"orchestration_id", "dispatch_nonce"}
        prefetch_inputs = (
            set(_PREFETCH_INPUTS) if batch in _PREFETCH_BATCHES else set()
        )
        expected_trigger_inputs = identity_inputs | prefetch_inputs
        for trigger_name in sorted(expected_triggers):
            trigger = _mapping(
                triggers.get(trigger_name),
                f"batch {batch} {trigger_name} trigger",
            )
            trigger_inputs = _mapping(
                trigger.get("inputs"),
                f"batch {batch} {trigger_name} inputs",
            )
            if set(trigger_inputs) != expected_trigger_inputs:
                raise ContractError(
                    f"batch {batch} strict orchestration inputs are not exact"
                )
            for input_name in sorted(identity_inputs):
                declaration = _mapping(
                    trigger_inputs.get(input_name),
                    f"batch {batch} {trigger_name} input {input_name}",
                )
                if (
                    declaration.get("required") is not True
                    or declaration.get("type") != "string"
                    or "default" in declaration
                ):
                    raise ContractError(
                        f"batch {batch} {trigger_name} input {input_name} "
                        "must be a required string without a default"
                    )
            for input_name in sorted(prefetch_inputs):
                declaration = _mapping(
                    trigger_inputs.get(input_name),
                    f"batch {batch} {trigger_name} input {input_name}",
                )
                if (
                    declaration.get("required") is not False
                    or declaration.get("type") != "string"
                    or "default" in declaration
                ):
                    raise ContractError(
                        f"batch {batch} {trigger_name} input {input_name} "
                        "must preserve the reviewed optional string contract "
                        "without a default"
                    )

        expected_prefetch_jobs = _PREFETCH_JOB_BINDINGS.get(
            batch, frozenset()
        )
        observed_prefetch_jobs: set[str] = set()
        for job, raw_definition in package_jobs:
            job_definition = _mapping(
                raw_definition, f"batch {batch} job {job}"
            )
            raw_inputs = job_definition.get("with")
            if job in expected_prefetch_jobs:
                job_inputs = _mapping(
                    raw_inputs, f"batch {batch} job {job} prefetch inputs"
                )
                if dict(job_inputs) != _PREFETCH_FORWARDING:
                    raise ContractError(
                        f"batch {batch} job {job} prefetch forwarding is not exact"
                    )
                observed_prefetch_jobs.add(job)
            elif isinstance(raw_inputs, Mapping) and set(raw_inputs).intersection(
                _PREFETCH_INPUTS
            ):
                raise ContractError(
                    f"batch {batch} job {job} has unreviewed prefetch forwarding"
                )
        if observed_prefetch_jobs != expected_prefetch_jobs:
            raise ContractError(
                f"batch {batch} prefetch job set is not exact"
            )
    return BatchDefinition(
        batch=batch,
        workflow_path=f".github/workflows/{path.name}",
        workflow_name=workflow_name,
        artifact_name=artifact_name,
        packages=tuple(registrations),
        external_actions=tuple(sorted(external_actions)),
        local_actions=tuple(sorted(local_actions)),
    )


def _yaml_mapping(raw: bytes, label: str) -> Mapping[str, Any]:
    if len(raw) > 2_097_152:
        raise ContractError(f"{label} exceeds its size limit")
    try:
        text = raw.decode("utf-8")
        payload = yaml.load(text, Loader=_UniqueSafeLoader)
    except (
        UnicodeDecodeError,
        yaml.YAMLError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise ContractError(f"{label} is not safe, bounded YAML") from exc
    mapping = _mapping(payload, label)
    _validate_json_shape(mapping)
    return mapping


def _collect_reachable_action_references(
    payload: object, label: str, *, root: Path
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    external, local = _collect_uses_references(payload, label)
    external.update(_collect_workflow_container_references(payload, label))
    reachable_local: set[str] = set()
    cache: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for reference in local:
        parts = PurePosixPath(reference.removeprefix("./")).parts
        if parts[:2] == (".github", "actions"):
            nested_external, nested_local = _resolve_local_action_references(
                reference,
                root=root,
                cache=cache,
                active=set(),
            )
            external.update(nested_external)
            reachable_local.update(nested_local)
    return tuple(sorted(external)), tuple(sorted(reachable_local))


def _collect_workflow_container_references(payload: object, label: str) -> set[str]:
    workflow = _mapping(payload, label)
    jobs = _mapping(workflow.get("jobs"), f"{label} jobs")
    references: set[str] = set()
    for job_name, raw_job in jobs.items():
        job = _mapping(raw_job, f"{label} job {job_name}")
        if "container" in job:
            references.add(
                _normalize_container_reference(
                    job["container"], f"{label} job {job_name} container"
                )
            )
        if "services" not in job:
            continue
        services = _mapping(job["services"], f"{label} job {job_name} services")
        for service_name, raw_service in services.items():
            service = _mapping(
                raw_service, f"{label} job {job_name} service {service_name}"
            )
            references.add(
                _normalize_container_reference(
                    service, f"{label} job {job_name} service {service_name}"
                )
            )
    return references


def _normalize_container_reference(value: object, label: str) -> str:
    if isinstance(value, Mapping):
        image = value.get("image")
    else:
        image = value
    image = _bounded_text(image, f"{label} image", 1_024)
    if image.startswith("docker://"):
        return image
    return f"docker://{image}"


def _collect_uses_references(payload: object, label: str) -> tuple[set[str], set[str]]:
    external: set[str] = set()
    local_references: set[str] = set()
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key == "uses":
                    if not isinstance(item, str):
                        raise ContractError(f"{label} contains a non-text uses value")
                    if item.startswith("./"):
                        local = PurePosixPath(item.removeprefix("./"))
                        local_prefix = local.parts[:2]
                        if (
                            "\\" in item
                            or item != f"./{local.as_posix()}"
                            or any(part in {"", ".", ".."} for part in local.parts)
                            or len(local.parts) < 3
                            or local_prefix
                            not in {
                                (".github", "actions"),
                                (".github", "workflows"),
                            }
                            or local_prefix == (".github", "workflows")
                            and len(local.parts) != 3
                        ):
                            raise ContractError(
                                f"{label} contains an unsafe local uses reference"
                            )
                        local_references.add(item)
                    else:
                        external.add(item)
                else:
                    stack.append(item)
        elif isinstance(value, list):
            stack.extend(value)
    return external, local_references


def _resolve_local_action_references(
    reference: str,
    *,
    root: Path,
    cache: dict[str, tuple[tuple[str, ...], tuple[str, ...]]],
    active: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if reference in cache:
        return cache[reference]
    if reference in active or len(active) >= 64 or len(cache) >= 256:
        raise ContractError("local action graph is cyclic or exceeds its limit")
    active.add(reference)
    parts = PurePosixPath(reference.removeprefix("./")).parts
    action_root = _real_directory(root.joinpath(*parts), f"local action {reference}")
    candidates = [
        candidate
        for candidate in (action_root / "action.yml", action_root / "action.yaml")
        if candidate.exists()
    ]
    if len(candidates) != 1:
        raise ContractError(
            f"local action {reference} must contain exactly one action manifest"
        )
    raw = _read_regular_file(
        candidates[0],
        root=root,
        label=f"local action manifest {reference}",
        maximum_bytes=MAX_WORKFLOW_FILE_BYTES,
    )
    action = _yaml_mapping(raw, f"local action manifest {reference}")
    runs = _mapping(action.get("runs"), f"local action runs {reference}")
    if (
        runs.get("using") != "composite"
        or not isinstance(runs.get("steps"), list)
        or not runs["steps"]
    ):
        raise ContractError(
            f"local action {reference} must be a composite action with steps"
        )
    external, nested_local = _collect_uses_references(
        action, f"local action manifest {reference}"
    )
    reachable_local = {reference}
    for nested in nested_local:
        nested_parts = PurePosixPath(nested.removeprefix("./")).parts
        if nested_parts[:2] != (".github", "actions"):
            raise ContractError("a local action cannot invoke a reusable workflow")
        nested_external, nested_reachable = _resolve_local_action_references(
            nested,
            root=root,
            cache=cache,
            active=active,
        )
        external.update(nested_external)
        reachable_local.update(nested_reachable)
    active.remove(reference)
    resolved = tuple(sorted(external)), tuple(sorted(reachable_local))
    cache[reference] = resolved
    return resolved


def _is_immutable_external_action(reference: str) -> bool:
    return bool(
        _IMMUTABLE_ACTION_RE.fullmatch(reference)
        or _IMMUTABLE_DOCKER_RE.fullmatch(reference)
    )


def _validate_test_details(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 6:
        raise ContractError("tests.details must contain exactly six records")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value, start=1):
        detail = _mapping(raw, f"test detail {index}")
        keys = set(detail)
        if not _DETAIL_REQUIRED_KEYS <= keys or not keys <= _DETAIL_ALLOWED_KEYS:
            raise ContractError(f"test detail {index} has missing or unexpected keys")
        name = _bounded_text(detail["name"], f"test detail {index} name", 300)
        if index <= 5 and not name.startswith(f"Test {index} -"):
            raise ContractError(f"baseline detail {index} is not Test {index}")
        if index == 6 and not (
            name.startswith("Test 6 -") or name.startswith("Regression ")
        ):
            raise ContractError("sixth detail is not the regression validation lane")
        if index == 6 and "decision" not in detail:
            raise ContractError("Test 6 detail must contain its canonical decision")
        status_value = detail["status"]
        if status_value not in {"passed", "failed", "skipped"}:
            raise ContractError(f"test detail {index} has invalid status")
        if index <= 5 and status_value == "skipped":
            raise ContractError("baseline tests 1-5 must never be skipped")
        duration = _nonnegative_int(
            detail["duration_seconds"], "detail duration_seconds"
        )
        url = _bounded_text(detail["url"], "detail url", 2_048)
        normalized_detail = dict(detail)
        normalized_detail.update(
            {
                "name": name,
                "status": status_value,
                "duration_seconds": duration,
                "url": url,
            }
        )
        if index == 6:
            normalized_detail["decision"] = _decision(
                detail["decision"], label="Test 6 detail decision"
            )
        for key in keys - _DETAIL_REQUIRED_KEYS:
            _bounded_text(
                detail[key],
                f"test detail {index} {key}",
                MAX_DETAIL_TEXT,
                allow_empty=True,
            )
        normalized.append(normalized_detail)
    return normalized


def _extract_verified_archive(raw: bytes, destination: Path) -> None:
    _prevalidate_zip_directory(raw)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), mode="r")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ContractError("artifact archive is not a valid ZIP file") from exc
    with archive:
        try:
            members = archive.infolist()
        except (UnicodeDecodeError, zipfile.BadZipFile) as exc:
            raise ContractError("artifact archive directory is malformed") from exc
        if not members or len(members) > MAX_BATCH_ENTRIES:
            raise ContractError("artifact archive has an invalid member count")
        seen: set[str] = set()
        normalized_names: set[str] = set()
        member_kinds: dict[str, bool] = {}
        total_size = 0
        validated: list[tuple[zipfile.ZipInfo, PurePosixPath, bool]] = []
        allowed_compression = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        for member in members:
            name = member.filename
            if (
                not name
                or "\x00" in name
                or "\\" in name
                or name.startswith("/")
                or member.flag_bits & 0x1
                or member.compress_type not in allowed_compression
            ):
                raise ContractError("artifact archive contains an unsafe member")
            stripped_name = name[:-1] if name.endswith("/") else name
            raw_parts = stripped_name.split("/")
            relative = PurePosixPath(stripped_name)
            if (
                not stripped_name
                or any(part in {"", ".", ".."} for part in raw_parts)
                or tuple(raw_parts) != relative.parts
                or len(relative.parts) > 2
                or ":" in relative.parts[0]
            ):
                raise ContractError("artifact archive member path is unsafe")
            canonical = relative.as_posix()
            normalized = unicodedata.normalize("NFC", canonical).casefold()
            if canonical in seen or normalized in normalized_names:
                raise ContractError("artifact archive contains duplicate paths")
            seen.add(canonical)
            normalized_names.add(normalized)
            mode = (member.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            is_directory = member.is_dir()
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ContractError("artifact archive contains a link or special file")
            if is_directory and file_type == stat.S_IFREG:
                raise ContractError("artifact archive directory has file metadata")
            if not is_directory and file_type == stat.S_IFDIR:
                raise ContractError("artifact archive file has directory metadata")
            if is_directory and len(relative.parts) != 1:
                raise ContractError("artifact archive directory depth is invalid")
            if is_directory and (
                member.file_size != 0 or member.compress_size != 0 or member.CRC != 0
            ):
                raise ContractError("artifact archive directory contains payload data")
            if not is_directory:
                total_size += member.file_size
                if (
                    canonical == BATCH_ATTESTATION_NAME
                    and member.file_size > MAX_BATCH_ATTESTATION_BYTES
                ):
                    raise ContractError("artifact attestation exceeds its size limit")
                if (
                    canonical != BATCH_ATTESTATION_NAME
                    and member.file_size > MAX_RESULT_BYTES
                ):
                    raise ContractError(
                        "artifact archive member exceeds its size limit"
                    )
                if total_size > MAX_BATCH_BYTES:
                    raise ContractError(
                        "artifact archive extracted size exceeds the limit"
                    )
            member_kinds[canonical] = is_directory
            validated.append((member, relative, is_directory))

        for _, relative, _ in validated:
            if len(relative.parts) == 2:
                parent = relative.parts[0]
                if parent in member_kinds and not member_kinds[parent]:
                    raise ContractError(
                        "artifact archive parent path is not a directory"
                    )

        for member, relative, is_directory in sorted(
            validated,
            key=lambda item: (not item[2], len(item[1].parts), item[1].as_posix()),
        ):
            target = destination.joinpath(*relative.parts)
            if is_directory:
                target.mkdir(mode=0o700)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor: int | None = None
            written = 0
            try:
                descriptor = os.open(target, flags, 0o600)
                with (
                    archive.open(member, mode="r") as source,
                    os.fdopen(descriptor, "wb") as output,
                ):
                    descriptor = None
                    while True:
                        chunk = source.read(65_536)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > member.file_size or written > MAX_BATCH_BYTES:
                            raise ContractError(
                                "artifact archive expanded beyond declared size"
                            )
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
                raise ContractError(
                    "could not safely extract artifact archive"
                ) from exc
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            if written != member.file_size:
                raise ContractError(
                    "artifact archive member size changed during extraction"
                )


def _prevalidate_zip_directory(raw: bytes) -> None:
    """Bound the central directory before Python allocates ZipInfo objects."""
    eocd_signature = b"PK\x05\x06"
    search_start = max(0, len(raw) - (65_535 + 22))
    eocd_offset = raw.rfind(eocd_signature, search_start)
    if eocd_offset < 0 or eocd_offset + 22 != len(raw):
        raise ContractError("artifact archive is missing a canonical ZIP directory")
    fields = struct.unpack_from("<4s4H2LH", raw, eocd_offset)
    eocd = fields[1:]

    (
        disk_number,
        directory_disk,
        entries_on_disk,
        entry_count,
        directory_size,
        directory_offset,
        comment_size,
    ) = eocd
    if (
        disk_number != 0
        or directory_disk != 0
        or entries_on_disk != entry_count
        or entry_count < 1
        or entry_count > MAX_BATCH_ENTRIES
        or directory_size > MAX_ZIP_CENTRAL_DIRECTORY_BYTES
        or comment_size != 0
        or directory_offset + directory_size != eocd_offset
    ):
        raise ContractError("artifact ZIP directory exceeds the bounded contract")
    if (
        entry_count == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    ):
        raise ContractError("ZIP64 artifacts are outside the bounded contract")

    position = directory_offset
    directory_end = directory_offset + directory_size
    parsed_entries = 0
    while position < directory_end:
        if (
            position + 46 > directory_end
            or raw[position : position + 4] != b"PK\x01\x02"
        ):
            raise ContractError("artifact ZIP central directory is malformed")
        (
            name_size,
            extra_size,
            member_comment_size,
            member_disk,
        ) = struct.unpack_from("<4H", raw, position + 28)
        compressed_size, uncompressed_size = struct.unpack_from(
            "<2L", raw, position + 20
        )
        local_header_offset = struct.unpack_from("<L", raw, position + 42)[0]
        if (
            not name_size
            or name_size > MAX_ZIP_MEMBER_NAME_BYTES
            or extra_size > MAX_ZIP_EXTRA_BYTES
            or member_comment_size > MAX_ZIP_COMMENT_BYTES
            or member_disk != 0
            or compressed_size == 0xFFFFFFFF
            or uncompressed_size == 0xFFFFFFFF
            or local_header_offset == 0xFFFFFFFF
        ):
            raise ContractError("artifact ZIP member metadata is outside the contract")
        position += 46 + name_size + extra_size + member_comment_size
        parsed_entries += 1
        if position > directory_end or parsed_entries > MAX_BATCH_ENTRIES:
            raise ContractError("artifact ZIP central directory is malformed")
    if position != directory_end or parsed_entries != entry_count:
        raise ContractError("artifact ZIP entry count does not match its directory")


def _inventory(root: Path) -> tuple[dict[Path, int], set[Path]]:
    files: dict[Path, int] = {}
    directories: set[Path] = set()
    entries = 0
    total_bytes = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        if depth > 2:
            raise ContractError("batch artifact directory depth exceeds the limit")
        try:
            children = list(os.scandir(directory))
        except OSError as exc:
            raise ContractError("could not inspect batch artifact") from exc
        for child in children:
            entries += 1
            if entries > MAX_BATCH_ENTRIES:
                raise ContractError("batch artifact entry count exceeds the limit")
            try:
                metadata = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise ContractError("could not stat batch artifact entry") from exc
            relative = Path(child.path).relative_to(root)
            if stat.S_ISLNK(metadata.st_mode):
                raise ContractError(f"batch artifact contains a symlink: {relative}")
            if stat.S_ISDIR(metadata.st_mode):
                directories.add(relative)
                stack.append((Path(child.path), depth + 1))
            elif stat.S_ISREG(metadata.st_mode):
                if metadata.st_nlink != 1:
                    raise ContractError(
                        f"batch artifact contains a hard-linked file: {relative}"
                    )
                total_bytes += metadata.st_size
                if total_bytes > MAX_BATCH_BYTES:
                    raise ContractError(
                        "batch artifact extracted size exceeds the limit"
                    )
                files[relative] = metadata.st_size
            else:
                raise ContractError(
                    f"batch artifact contains a special file: {relative}"
                )
    return files, directories


def _json_bytes(raw: bytes, label: str, maximum_bytes: int) -> tuple[object, str]:
    if len(raw) > maximum_bytes:
        raise ContractError(f"{label} exceeds its size limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{label} is not UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_int=_bounded_json_int,
            parse_float=lambda value: (_ for _ in ()).throw(
                ContractError(f"JSON floating point number is not accepted: {value}")
            ),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ContractError(f"JSON contains non-finite number {value}")
            ),
        )
        _validate_json_shape(payload)
    except (
        json.JSONDecodeError,
        ContractError,
        RecursionError,
        ValueError,
        OverflowError,
    ) as exc:
        raise ContractError(f"{label} is not valid unique-key JSON") from exc
    return payload, text


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"JSON object contains duplicate key {key!r}")
        result[key] = value
    return result


def _bounded_json_int(value: str) -> int:
    if len(value) > 20:
        raise ContractError("JSON integer exceeds the numeric resource limit")
    parsed = int(value)
    if parsed < -MAX_INTEGER or parsed > MAX_INTEGER:
        raise ContractError("JSON integer exceeds the numeric resource limit")
    return parsed


def _validate_json_shape(payload: object) -> None:
    nodes = 0
    stack: list[tuple[object, int]] = [(payload, 0)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise ContractError("JSON node count exceeds the limit")
        if depth > MAX_JSON_DEPTH:
            raise ContractError("JSON nesting depth exceeds the limit")
        if isinstance(value, Mapping):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)


def _read_regular_file(
    path: Path, *, root: Path, label: str, maximum_bytes: int
) -> bytes:
    try:
        metadata = path.lstat()
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"could not inspect {label}") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise ContractError(f"{label} must be a regular non-symlink file")
    if not resolved_path.is_relative_to(resolved_root):
        raise ContractError(f"{label} escapes its trusted root")
    if metadata.st_size > maximum_bytes:
        raise ContractError(f"{label} exceeds its size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or opened.st_size > maximum_bytes
        ):
            raise ContractError(f"{label} changed during verification")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum_bytes:
            raise ContractError(f"{label} exceeds its size limit")
        final = os.fstat(descriptor)
        current = path.lstat()
        if (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ContractError(f"{label} changed during verification")
        return raw
    except OSError as exc:
        raise ContractError(f"could not read {label}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _real_directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"could not inspect {label}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ContractError(f"{label} must be a real directory")
    return resolved


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return value


def _api_pages(value: object, label: str) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        pages = [value]
    elif isinstance(value, list) and value:
        pages = value
    else:
        raise ContractError(f"{label} is missing or malformed")
    if len(pages) > MAX_API_PAGES:
        raise ContractError(f"{label} exceeds the page limit")
    return [dict(_mapping(page, f"{label} page")) for page in pages]


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    keys = set(value)
    if keys != expected:
        raise ContractError(
            f"{label} has missing or unexpected keys: "
            f"missing={sorted(expected - keys)}, extra={sorted(keys - expected)}"
        )


def _positive_int(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_INTEGER
    ):
        raise ContractError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_INTEGER
    ):
        raise ContractError(f"{label} must be a non-negative integer")
    return value


def _bounded_text(
    value: object, label: str, maximum: int, *, allow_empty: bool = False
) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ContractError(f"{label} must be bounded text")
    if (
        value != value.strip()
        or (not value and not allow_empty)
        or any(ord(character) < 32 for character in value)
    ):
        raise ContractError(
            f"{label} contains whitespace-only, padded, or control text"
        )
    return value


def _slug(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SLUG_RE.fullmatch(value):
        raise ContractError(f"{label} is not canonical")
    return value


def _decision(value: object, *, label: str = "regression_decision") -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 100
        or not re.fullmatch(r"[a-z][a-z0-9_]*", value, re.ASCII)
    ):
        raise ContractError(f"{label} is not canonical")
    return value


def _nonce(value: object, label: str) -> str:
    if not isinstance(value, str) or not _NONCE_RE.fullmatch(value):
        raise ContractError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _repository(value: object) -> str:
    if not isinstance(value, str) or not _REPOSITORY_RE.fullmatch(value):
        raise ContractError("repository is not canonical")
    return value


def _branch(value: object) -> str:
    if (
        not isinstance(value, str)
        or not _BRANCH_RE.fullmatch(value)
        or ".." in value
        or "//" in value
        or value.endswith(("/", "."))
    ):
        raise ContractError("branch is not canonical")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ContractError(f"{label} must be a full lowercase Git SHA")
    return value


def _orchestration_id(value: object) -> str:
    if not isinstance(value, str) or not _ORCHESTRATION_RE.fullmatch(value):
        raise ContractError("orchestration_id is not canonical")
    return value


def _timestamp(value: object, label: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or not _RFC3339_RE.fullmatch(value):
        raise ContractError(f"{label} must be canonical RFC3339 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} is not a real timestamp") from exc
    if parsed.utcoffset() is None:
        raise ContractError(f"{label} must include a timezone")
    return value, parsed


def _load_manifest_file(
    path: Path,
    topology: Sequence[BatchDefinition],
    *,
    expected_repository: str,
    expected_branch: str,
    expected_sha: str,
    expected_orchestration_id: str,
    expected_dispatch_nonces: Sequence[str],
    expected_not_before: str,
    expected_not_after: str,
) -> dict[str, Any]:
    root = _real_directory(path.parent, "manifest parent")
    raw = _read_regular_file(
        path, root=root, label="manifest", maximum_bytes=MAX_MANIFEST_BYTES
    )
    return validate_manifest_text(
        raw,
        topology=topology,
        expected_repository=expected_repository,
        expected_branch=expected_branch,
        expected_sha=expected_sha,
        expected_orchestration_id=expected_orchestration_id,
        expected_dispatch_nonces=expected_dispatch_nonces,
        expected_not_before=expected_not_before,
        expected_not_after=expected_not_after,
    )


def _parse_expected_nonce_arguments(
    values: Sequence[str], topology: Sequence[BatchDefinition]
) -> tuple[str, ...]:
    assignments = _parse_batch_assignments(
        values, topology, label="expected dispatch nonce"
    )
    return tuple(
        _nonce(assignments[batch], f"expected dispatch nonce {batch}")
        for batch in range(1, len(topology) + 1)
    )


def _parse_artifact_archive_arguments(
    values: Sequence[str], topology: Sequence[BatchDefinition]
) -> tuple[Path, ...]:
    assignments = _parse_batch_assignments(values, topology, label="artifact archive")
    return tuple(
        Path(_bounded_text(assignments[batch], f"artifact archive {batch}", 4_096))
        for batch in range(1, len(topology) + 1)
    )


def _parse_batch_assignments(
    values: Sequence[str],
    topology: Sequence[BatchDefinition],
    *,
    label: str,
) -> dict[int, str]:
    if isinstance(values, (str, bytes)):
        raise ContractError(f"{label} assignments are malformed")
    assignments: dict[int, str] = {}
    for value in values:
        if not isinstance(value, str) or "=" not in value:
            raise ContractError(f"{label} must use BATCH=VALUE syntax")
        batch_text, assigned = value.split("=", 1)
        if not re.fullmatch(r"[1-9][0-9]*", batch_text, re.ASCII) or not assigned:
            raise ContractError(f"{label} must use canonical BATCH=VALUE syntax")
        batch = int(batch_text)
        if batch > len(topology) or batch in assignments:
            raise ContractError(f"{label} batch is unknown or duplicated")
        assignments[batch] = assigned
    expected_batches = set(range(1, len(topology) + 1))
    if set(assignments) != expected_batches:
        raise ContractError(f"{label} assignments must cover every batch exactly once")
    return assignments


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    topology = subparsers.add_parser("topology")
    topology.add_argument("--repository-root", type=Path, required=True)
    manifest = subparsers.add_parser("validate-manifest")
    manifest.add_argument("--repository-root", type=Path, required=True)
    manifest.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="trusted-parent manifest built only from authenticated GitHub API data",
    )
    verify = subparsers.add_parser("verify-batch")
    verify.add_argument("--repository-root", type=Path, required=True)
    verify.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="trusted-parent manifest built only from authenticated GitHub API data",
    )
    verify.add_argument("--batch", type=int, required=True)
    verify.add_argument("--artifact-archive", type=Path, required=True)
    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument("--repository-root", type=Path, required=True)
    aggregate.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="trusted-parent manifest built only from authenticated GitHub API data",
    )
    aggregate.add_argument(
        "--artifact-archive",
        dest="artifact_archives",
        action="append",
        required=True,
        metavar="BATCH=PATH",
        help="exact downloaded archive path for one batch; provide every batch once",
    )
    for command in (manifest, verify, aggregate):
        command.add_argument("--expected-repository", required=True)
        command.add_argument("--expected-branch", required=True)
        command.add_argument("--expected-sha", required=True)
        command.add_argument(
            "--expected-orchestration-id",
            required=True,
            help="trusted current parent run identity, for example orchestration-123-1",
        )
        command.add_argument(
            "--expected-dispatch-nonce",
            dest="expected_dispatch_nonce_arguments",
            action="append",
            required=True,
            metavar="BATCH=NONCE",
            help="trusted 64-hex nonce for one batch; provide every batch once",
        )
        command.add_argument(
            "--expected-not-before",
            required=True,
            metavar="RFC3339",
            help="trusted orchestration window start",
        )
        command.add_argument(
            "--expected-not-after",
            required=True,
            metavar="RFC3339",
            help="trusted orchestration window end; window must not exceed 24 hours",
        )
    return parser


def _main(arguments: Sequence[str]) -> int:
    args = _build_parser().parse_args(arguments)
    if args.command in {"validate-manifest", "verify-batch", "aggregate"}:
        validate_checkout_binding(args.repository_root, args.expected_sha)
        topology = discover_topology_at_commit(args.repository_root, args.expected_sha)
        expected_dispatch_nonces = _parse_expected_nonce_arguments(
            args.expected_dispatch_nonce_arguments, topology
        )
    else:
        topology = discover_topology(args.repository_root)
    if args.command == "topology":
        print(canonical_json(topology_payload(topology)))
    elif args.command == "validate-manifest":
        manifest = _load_manifest_file(
            args.manifest,
            topology,
            expected_repository=args.expected_repository,
            expected_branch=args.expected_branch,
            expected_sha=args.expected_sha,
            expected_orchestration_id=args.expected_orchestration_id,
            expected_dispatch_nonces=expected_dispatch_nonces,
            expected_not_before=args.expected_not_before,
            expected_not_after=args.expected_not_after,
        )
        print(canonical_json(manifest))
    elif args.command == "verify-batch":
        manifest = _load_manifest_file(
            args.manifest,
            topology,
            expected_repository=args.expected_repository,
            expected_branch=args.expected_branch,
            expected_sha=args.expected_sha,
            expected_orchestration_id=args.expected_orchestration_id,
            expected_dispatch_nonces=expected_dispatch_nonces,
            expected_not_before=args.expected_not_before,
            expected_not_after=args.expected_not_after,
        )
        proof = validate_batch_artifact(
            artifact_archive=args.artifact_archive,
            manifest=manifest,
            topology=topology,
            batch=args.batch,
        )
        print(canonical_json(proof))
    elif args.command == "aggregate":
        manifest = _load_manifest_file(
            args.manifest,
            topology,
            expected_repository=args.expected_repository,
            expected_branch=args.expected_branch,
            expected_sha=args.expected_sha,
            expected_orchestration_id=args.expected_orchestration_id,
            expected_dispatch_nonces=expected_dispatch_nonces,
            expected_not_before=args.expected_not_before,
            expected_not_after=args.expected_not_after,
        )
        archives = _parse_artifact_archive_arguments(args.artifact_archives, topology)
        aggregate = build_aggregate_attestation(
            manifest=manifest,
            topology=topology,
            artifact_archives=archives,
        )
        print(canonical_json(aggregate))
    return 0


def main() -> int:
    try:
        return _main(sys.argv[1:])
    except ContractError as exc:
        print(f"contract error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
