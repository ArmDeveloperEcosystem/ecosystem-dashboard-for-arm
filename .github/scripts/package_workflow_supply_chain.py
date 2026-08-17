#!/usr/bin/env python3
"""Apply and validate package-workflow supply-chain controls.

The authoritative workflow set is derived only from the 22 batch wrappers.
This script intentionally has no network access; the separately reviewed lock
file records the GitHub API and git-ls-remote resolution evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tarfile
from collections import Counter
from pathlib import Path
from typing import Iterable

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
EXACT_RUN_SPEC = importlib.util.spec_from_file_location(
    "dashboard_exact_run_aggregation",
    SCRIPT_DIRECTORY / "exact_run_aggregation.py",
)
if EXACT_RUN_SPEC is None or EXACT_RUN_SPEC.loader is None:
    raise RuntimeError("could not load the exact-run contract")
exact_run = importlib.util.module_from_spec(EXACT_RUN_SPEC)
sys.modules[EXACT_RUN_SPEC.name] = exact_run
EXACT_RUN_SPEC.loader.exec_module(exact_run)


EXPECTED_BATCHES = 22
EXPECTED_WORKFLOWS = 960
EXPECTED_EXTERNAL_USES = 1130
EXPECTED_CONTAINER_USES = 3
SOURCE_COMMIT = "73155d0d3a3dc73da08c62bc2bb7eccf281c6008"
LOCK_NAME = "package_workflow_action_lock.json"
MAX_SOURCE_ARCHIVE_BYTES = 67_108_864
EXPECTED_MIGRATION_CHANGES = {
    "permission_blocks_removed": 35,
    "permissions": 978,
    "pinned_uses": 1128,
    "checkout_credentials": 981,
    "container_pins": 3,
    "summary_permissions": 21,
    "batch_root_permissions_narrowed": 3,
    "normalized_pinned_comments": 2,
}

REGISTRATION_RE = re.compile(
    r"^\s*uses:\s*(\./\.github/workflows/test-[^\s#]+\.yml)\s*(?:#.*)?$"
)
USES_RE = re.compile(
    r"^(?P<space>\s*)(?P<dash>-\s*)?uses:\s*"
    r"(?P<spec>[^\s#]+)(?P<tail>[ \t]*(?:#.*)?)"
    r"(?P<eol>\r?\n?)$"
)
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DOCKER_DIGEST_RE = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")
ORIGINAL_COMMENT_RE = re.compile(r"^\s+# original: (?P<ref>[^\s#]+)\s*$")
VERSION_COMMENT_RE = re.compile(r"^\s+# (?P<ref>v[^\s#]+)\s*$")
CONTAINER_RE = re.compile(
    r"^(?P<space>\s*)(?P<key>image|container):\s*"
    r"(?P<spec>[^\s#]+)(?P<tail>[ \t]*(?:#.*)?)"
    r"(?P<eol>\r?\n?)$"
)


class ContractError(RuntimeError):
    """Raised when the package-workflow contract is not exact."""


def container_repository(reference: str) -> str:
    """Return the registry/repository identity without a mutable tag."""
    value = reference.removeprefix("docker://")
    if not value or any(character.isspace() for character in value):
        raise ContractError(f"invalid container reference: {reference!r}")
    value = value.split("@", 1)[0]
    slash = value.rfind("/")
    colon = value.rfind(":")
    if colon > slash:
        value = value[:colon]
    if not value or value.endswith("/"):
        raise ContractError(f"invalid container repository: {reference!r}")
    return value


def validate_action_lock_entry(entry: object) -> tuple[str, str]:
    if not isinstance(entry, dict):
        raise ContractError("action lock entries must be objects")
    expected_keys = {
        "original_ref",
        "occurrences",
        "repository",
        "repository_id",
        "action_path",
        "action_file",
        "requested_ref",
        "ref_type",
        "resolved_commit",
        "resolution_chain",
        "github_api_repository_confirmed",
        "github_api_commit_confirmed",
        "action_file_confirmed_at_commit",
        "git_ls_remote",
        "github_commit_verification",
    }
    if set(entry) != expected_keys:
        raise ContractError("action lock entry has missing or unexpected evidence")
    original = entry.get("original_ref")
    if not isinstance(original, str):
        raise ContractError(f"invalid original ref: {original!r}")
    action, repository, action_path, requested_ref = split_github_action(original)
    if (
        entry.get("repository") != repository
        or entry.get("action_path") != action_path
        or entry.get("requested_ref") != requested_ref
        or entry.get("action_file")
        != (f"{action_path}/action.yml" if action_path else "action.yml")
    ):
        raise ContractError(f"action identity evidence contradicts {original}")
    repository_id = entry.get("repository_id")
    occurrences = entry.get("occurrences")
    commit = entry.get("resolved_commit")
    ref_type = entry.get("ref_type")
    chain = entry.get("resolution_chain")
    if (
        not isinstance(repository_id, int)
        or repository_id < 1
        or not isinstance(occurrences, int)
        or occurrences < 1
        or not isinstance(commit, str)
        or not FULL_SHA_RE.fullmatch(commit)
        or ref_type not in {"branch", "lightweight_tag", "annotated_tag"}
        or not isinstance(chain, list)
    ):
        raise ContractError(f"invalid resolution evidence for {original}")
    if any(
        entry.get(key) is not True
        for key in (
            "github_api_repository_confirmed",
            "github_api_commit_confirmed",
            "action_file_confirmed_at_commit",
        )
    ):
        raise ContractError(f"GitHub API evidence is incomplete for {original}")
    remote = entry.get("git_ls_remote")
    if not isinstance(remote, dict) or set(remote) != {
        "ref_object",
        "peeled_commit",
        "matches_github_api",
    }:
        raise ContractError(f"git ls-remote evidence is malformed for {original}")
    if (
        remote.get("matches_github_api") is not True
        or remote.get("peeled_commit") != commit
        or not isinstance(remote.get("ref_object"), str)
        or not FULL_SHA_RE.fullmatch(str(remote["ref_object"]))
    ):
        raise ContractError(f"git ls-remote evidence contradicts {original}")
    if ref_type == "annotated_tag":
        if not chain or chain[-1] != {
            "tag_object": remote["ref_object"],
            "target_type": "commit",
            "target_sha": commit,
        }:
            raise ContractError(f"annotated-tag evidence is incomplete for {original}")
    elif chain or remote["ref_object"] != commit:
        raise ContractError(f"direct ref evidence contradicts {original}")
    verification = entry.get("github_commit_verification")
    if (
        not isinstance(verification, dict)
        or set(verification)
        != {"verified", "reason", "signature_present", "payload_present"}
        or not isinstance(verification.get("verified"), bool)
        or not isinstance(verification.get("reason"), str)
        or not verification["reason"]
        or not isinstance(verification.get("signature_present"), bool)
        or not isinstance(verification.get("payload_present"), bool)
    ):
        raise ContractError(f"commit verification evidence is malformed for {original}")
    if verification["verified"] and not (
        verification["signature_present"] and verification["payload_present"]
    ):
        raise ContractError(f"verified commit evidence is incomplete for {original}")
    return action, commit


def validate_container_lock_entry(entry: object) -> str:
    if not isinstance(entry, dict) or set(entry) != {
        "workflow",
        "original_ref",
        "repository",
        "resolved_ref",
        "resolved_digest",
        "arm64_digest",
        "media_type",
        "linux_arm64_confirmed",
        "observed_at_utc",
        "arm64_runtime_validation",
    }:
        raise ContractError("container lock entry has missing or unexpected evidence")
    workflow = entry.get("workflow")
    original = entry.get("original_ref")
    digest = entry.get("resolved_digest")
    arm64_digest = entry.get("arm64_digest")
    original_repository = (
        container_repository(original) if isinstance(original, str) else None
    )
    runtime = entry.get("arm64_runtime_validation")
    if (
        not isinstance(workflow, str)
        or not workflow.startswith(".github/workflows/test-")
        or not isinstance(original, str)
        or "@sha256:" in original
        or entry.get("repository") != original_repository
        or not isinstance(digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        or entry.get("resolved_ref") != f"{original_repository}@{digest}"
        or not isinstance(arm64_digest, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", arm64_digest)
        or entry.get("media_type") != "application/vnd.oci.image.index.v1+json"
        or entry.get("linux_arm64_confirmed") is not True
        or not isinstance(entry.get("observed_at_utc"), str)
        or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            str(entry["observed_at_utc"]),
        )
        or not isinstance(runtime, dict)
        or set(runtime) != {"method", "result"}
        or not isinstance(runtime.get("method"), str)
        or not runtime["method"].strip()
        or runtime.get("result") != "passed"
    ):
        raise ContractError(f"invalid container lock entry: {entry!r}")
    return workflow


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def batch_paths(root: Path) -> list[Path]:
    return [
        root / ".github" / "workflows" / f"test-all-packages-batch{i}.yml"
        for i in range(1, EXPECTED_BATCHES + 1)
    ]


def registered_workflows(root: Path) -> list[Path]:
    registrations: list[Path] = []
    for batch in batch_paths(root):
        if not batch.is_file():
            raise ContractError(f"missing batch wrapper: {batch.relative_to(root)}")
        for line in batch.read_text(encoding="utf-8").splitlines():
            match = REGISTRATION_RE.match(line)
            if match:
                registrations.append(root / match.group(1)[2:])

    relative = [path.relative_to(root).as_posix() for path in registrations]
    duplicates = sorted(name for name, count in Counter(relative).items() if count != 1)
    missing = sorted(
        path.relative_to(root).as_posix()
        for path in registrations
        if not path.is_file()
    )
    if len(registrations) != EXPECTED_WORKFLOWS:
        raise ContractError(
            f"expected {EXPECTED_WORKFLOWS} registrations, found {len(registrations)}"
        )
    if duplicates:
        raise ContractError(f"duplicate registrations: {duplicates}")
    if missing:
        raise ContractError(f"missing registered workflows: {missing}")
    return registrations


def load_lock(root: Path) -> dict[str, object]:
    lock_path = root / ".github" / "scripts" / LOCK_NAME
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(
            f"cannot read {lock_path.relative_to(root)}: {exc}"
        ) from exc

    if lock.get("schema_version") != 3:
        raise ContractError("unsupported action lock schema")
    if lock.get("source_commit") != SOURCE_COMMIT:
        raise ContractError("action lock source commit is not the reviewed baseline")
    if lock.get("registered_workflows") != EXPECTED_WORKFLOWS:
        raise ContractError("action lock workflow count is not canonical")
    if lock.get("external_uses") != EXPECTED_EXTERNAL_USES:
        raise ContractError("action lock external-use count is not canonical")
    if lock.get("container_uses") != EXPECTED_CONTAINER_USES:
        raise ContractError("action lock container-use count is not canonical")
    if lock.get("unresolved_references") != []:
        raise ContractError("action lock contains unresolved references")
    for key in (
        "migration_parent_workflow_sha256",
        "hardened_topology_sha256",
        "hardened_workflow_sha256",
    ):
        value = lock.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ContractError(f"action lock {key} is not a canonical SHA-256")
    entries = lock.get("actions")
    if not isinstance(entries, list) or not entries:
        raise ContractError("action lock must contain a non-empty actions list")

    originals: set[str] = set()
    for entry in entries:
        validate_action_lock_entry(entry)
        original = entry["original_ref"]
        if original in originals:
            raise ContractError(f"invalid or duplicate original ref: {original!r}")
        originals.add(original)
    if sum(int(entry["occurrences"]) for entry in entries) != EXPECTED_EXTERNAL_USES:
        raise ContractError("action lock occurrence total is not canonical")

    containers = lock.get("containers")
    if not isinstance(containers, list) or len(containers) != EXPECTED_CONTAINER_USES:
        raise ContractError("container lock must contain exactly three entries")
    locations: set[str] = set()
    for entry in containers:
        workflow = validate_container_lock_entry(entry)
        if workflow in locations:
            raise ContractError(f"duplicate container lock workflow: {workflow}")
        locations.add(workflow)
    return lock


def lock_by_original(lock: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        entry["original_ref"]: entry
        for entry in lock["actions"]  # type: ignore[index]
    }


def container_lock_by_workflow(
    lock: dict[str, object],
) -> dict[str, dict[str, object]]:
    return {
        entry["workflow"]: entry
        for entry in lock["containers"]  # type: ignore[index]
    }


def permission_exceptions(lock: dict[str, object]) -> dict[str, dict[str, str]]:
    raw = lock.get("permission_exceptions")
    if not isinstance(raw, list):
        raise ContractError("action lock must contain permission_exceptions")
    exceptions: dict[str, dict[str, str]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ContractError("permission exceptions must be objects")
        workflow = entry.get("workflow")
        scopes = entry.get("job_scopes")
        reason = entry.get("reason")
        if (
            not isinstance(workflow, str)
            or workflow in exceptions
            or not isinstance(scopes, dict)
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ContractError(f"invalid permission exception: {entry!r}")
        normalized = {
            key: value
            for key, value in scopes.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if normalized != {"contents": "read", "packages": "read"}:
            raise ContractError(f"unsupported permission exception: {workflow}")
        exceptions[workflow] = normalized
    return exceptions


def split_github_action(spec: str) -> tuple[str, str, str, str]:
    if "@" not in spec:
        raise ContractError(f"external action has no ref: {spec}")
    action, ref = spec.rsplit("@", 1)
    parts = action.split("/")
    if len(parts) < 2 or not all(parts[:2]):
        raise ContractError(f"not a GitHub action reference: {spec}")
    owner_repo = "/".join(parts[:2])
    path = "/".join(parts[2:])
    return action, owner_repo, path, ref


def iter_uses(path: Path) -> Iterable[tuple[int, re.Match[str]]]:
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(keepends=True), start=1
    ):
        match = USES_RE.match(line)
        if match:
            yield number, match


def _step_end(
    lines: list[str], uses_index: int, match: re.Match[str]
) -> tuple[int, int]:
    leading = len(match.group("space"))
    sibling_indent = leading + (2 if match.group("dash") else 0)
    list_indent = max(0, sibling_indent - 2)
    index = uses_index + 1
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        indent = len(lines[index]) - len(lines[index].lstrip(" "))
        if indent < list_indent:
            break
        if indent == list_indent and lines[index].lstrip(" ").startswith("-"):
            break
        index += 1
    return index, sibling_indent


def _checkout_has_disabled_credentials(
    lines: list[str], uses_index: int, match: re.Match[str]
) -> bool:
    end, sibling_indent = _step_end(lines, uses_index, match)
    with_index = None
    for index in range(uses_index + 1, end):
        line = lines[index]
        indent = len(line) - len(line.lstrip(" "))
        if indent == sibling_indent and line.strip() == "with:":
            with_index = index
            break
    if with_index is None:
        return False

    for index in range(with_index + 1, end):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= sibling_indent:
            break
        if re.fullmatch(r"persist-credentials:\s*false", stripped):
            return True
        if stripped.startswith("persist-credentials:"):
            return False
    return False


def _add_checkout_credentials_control(
    lines: list[str], uses_index: int, match: re.Match[str]
) -> int:
    if _checkout_has_disabled_credentials(lines, uses_index, match):
        return 0

    end, sibling_indent = _step_end(lines, uses_index, match)
    with_index = None
    for index in range(uses_index + 1, end):
        line = lines[index]
        indent = len(line) - len(line.lstrip(" "))
        if indent == sibling_indent and line.strip() == "with:":
            with_index = index
            break
    newline = "\r\n" if lines[uses_index].endswith("\r\n") else "\n"
    if with_index is None:
        lines[uses_index + 1 : uses_index + 1] = [
            " " * sibling_indent + "with:" + newline,
            " " * (sibling_indent + 2) + "persist-credentials: false" + newline,
        ]
    else:
        lines.insert(
            with_index + 1,
            " " * (sibling_indent + 2) + "persist-credentials: false" + newline,
        )
    return 1


def _add_root_permissions(lines: list[str], path: Path) -> int:
    if any(re.match(r"^permissions\s*:", line) for line in lines):
        return 0
    on_indexes = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^on:\s*(?:#.*)?$", line.rstrip("\r\n"))
    ]
    if len(on_indexes) != 1:
        raise ContractError(f"{path}: expected one top-level on key")
    index = on_indexes[0]
    newline = "\r\n" if lines[index].endswith("\r\n") else "\n"
    lines[index:index] = [
        "permissions:" + newline,
        "  contents: read" + newline,
        newline,
    ]
    return 1


def _normalize_batch_root_permissions(lines: list[str], path: Path) -> tuple[int, int]:
    root_indexes = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^permissions:\s*(?:#.*)?(?:\r?\n)?$", line)
    ]
    if not root_indexes:
        return _add_root_permissions(lines, path), 0
    if len(root_indexes) != 1:
        raise ContractError(f"{path}: expected at most one root permissions block")
    start = root_indexes[0]
    values = _permission_values(lines, start)
    if values == ["contents: read"]:
        return 0, 0
    if set(values) != {"actions: read", "contents: read"} or len(values) != 2:
        raise ContractError(f"{path}: unreviewed batch root permissions")
    end = _permission_block_end(lines, start)
    action_indexes = [
        index
        for index in range(start + 1, end)
        if lines[index].strip() == "actions: read"
    ]
    if len(action_indexes) != 1:
        raise ContractError(f"{path}: could not narrow batch root permissions")
    del lines[action_indexes[0]]
    return 0, 1


def _permission_block_end(lines: list[str], start: int) -> int:
    indent = len(lines[start]) - len(lines[start].lstrip(" "))
    index = start + 1
    while index < len(lines):
        stripped = lines[index].strip()
        current_indent = len(lines[index]) - len(lines[index].lstrip(" "))
        if stripped and current_indent <= indent:
            break
        index += 1
    return index


def _summary_job_bounds(lines: list[str], path: Path) -> tuple[int, int]:
    starts = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(r"  summary:\s*(?:\r?\n)?", line)
    ]
    if len(starts) != 1:
        raise ContractError(f"{path}: expected one summary job")
    start = starts[0]
    end = start + 1
    while end < len(lines):
        if re.match(r"^  [A-Za-z0-9_-]+:\s*(?:\r?\n)?$", lines[end]):
            break
        end += 1
    return start, end


def _batch_permission_workflow(
    path: Path,
    lines: list[str],
    permission_index: int,
) -> str:
    start = permission_index - 1
    while start >= 0 and re.fullmatch(
        r"  [A-Za-z0-9_-]+:\s*(?:\r?\n)?", lines[start]
    ) is None:
        start -= 1
    if start < 0 or lines[start].strip() == "summary:":
        raise ContractError(f"{path}: job permission block has no package job")
    end = start + 1
    while end < len(lines) and re.fullmatch(
        r"  [A-Za-z0-9_-]+:\s*(?:\r?\n)?", lines[end]
    ) is None:
        end += 1
    matches = [
        re.fullmatch(
            r"\s{4}uses:\s*(?P<workflow>\./\.github/workflows/test-[^\s#]+\.yml)"
            r"\s*(?:#.*)?",
            line,
        )
        for line in lines[start + 1 : end]
    ]
    workflows = [match.group("workflow") for match in matches if match is not None]
    if len(workflows) != 1:
        raise ContractError(f"{path}: permissioned package job must call one workflow")
    return workflows[0].removeprefix("./")


def _add_summary_permissions(lines: list[str], path: Path) -> int:
    start, end = _summary_job_bounds(lines, path)
    permission_indexes = [
        index
        for index in range(start + 1, end)
        if re.match(r"^    permissions:\s*(?:\r?\n)?$", lines[index])
    ]
    if permission_indexes:
        if len(permission_indexes) != 1:
            raise ContractError(f"{path}: summary permissions are ambiguous")
        return 0
    newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
    lines[start + 1 : start + 1] = [
        "    permissions:" + newline,
        "      actions: read" + newline,
        "      contents: read" + newline,
    ]
    return 1


def _remove_unneeded_job_permissions(
    root: Path,
    path: Path,
    lines: list[str],
    exceptions: dict[str, dict[str, str]],
) -> int:
    relative = path.relative_to(root).as_posix()
    removed = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if not re.match(r"^ +permissions:\s*(?:#.*)?(?:\r?\n)?$", line):
            index += 1
            continue
        end = _permission_block_end(lines, index)
        if relative in exceptions:
            index = end
            continue
        del lines[index:end]
        removed += 1
    return removed


def transform_content(
    root: Path,
    path: Path,
    content: str,
    entries: dict[str, dict[str, object]],
    exceptions: dict[str, dict[str, str]],
    *,
    package_workflow: bool,
    container_entry: dict[str, object] | None = None,
) -> tuple[str, Counter[str]]:
    lines = content.splitlines(keepends=True)
    changes: Counter[str] = Counter()
    if package_workflow:
        changes["permission_blocks_removed"] += _remove_unneeded_job_permissions(
            root, path, lines, exceptions
        )
        changes["permissions"] += _add_root_permissions(lines, path)
    else:
        changes["summary_permissions"] += _add_summary_permissions(lines, path)
        added, narrowed = _normalize_batch_root_permissions(lines, path)
        changes["permissions"] += added
        changes["batch_root_permissions_narrowed"] += narrowed

    index = 0
    while index < len(lines):
        match = USES_RE.match(lines[index])
        if not match:
            index += 1
            continue
        spec = match.group("spec")
        if spec.startswith("./"):
            index += 1
            continue
        if spec.startswith("docker://"):
            if not DOCKER_DIGEST_RE.fullmatch(spec):
                raise ContractError(f"{path}: unpinned Docker reference: {spec}")
            index += 1
            continue

        action, _, _, ref = split_github_action(spec)
        if FULL_SHA_RE.fullmatch(ref):
            pinned_spec = spec
            original_comment = ORIGINAL_COMMENT_RE.fullmatch(match.group("tail"))
            if original_comment is not None:
                original = original_comment.group("ref")
            else:
                version_comment = VERSION_COMMENT_RE.fullmatch(match.group("tail"))
                if version_comment is None:
                    raise ContractError(
                        f"{path}: immutable action lacks reviewed origin: {spec}"
                    )
                original = f"{action}@{version_comment.group('ref')}"
                newline = match.group("eol")
                lines[index] = (
                    lines[index][: match.start("tail")]
                    + f" # original: {original}{newline}"
                )
                changes["normalized_pinned_comments"] += 1
                match = USES_RE.match(lines[index])
                if match is None:
                    raise AssertionError("normalized uses line did not parse")
            entry = entries.get(original)
            if entry is None or entry["resolved_commit"] != ref:
                raise ContractError(
                    f"{path}: immutable action is absent from lock: {spec}"
                )
        else:
            entry = entries.get(spec)
            if entry is None:
                raise ContractError(f"{path}: unresolved external action: {spec}")
            pinned_spec = f"{action}@{entry['resolved_commit']}"
            if match.group("tail").strip():
                raise ContractError(
                    f"{path}: mutable action has an existing inline comment: {spec}"
                )
            newline = match.group("eol")
            lines[index] = (
                lines[index][: match.start("spec")]
                + pinned_spec
                + f" # original: {spec}{newline}"
            )
            changes["pinned_uses"] += 1
            match = USES_RE.match(lines[index])
            if match is None:
                raise AssertionError("rewritten uses line did not parse")

        _, owner_repo, _, _ = split_github_action(pinned_spec)
        if owner_repo.lower() == "actions/checkout":
            added = _add_checkout_credentials_control(lines, index, match)
            changes["checkout_credentials"] += added
            index += added
        index += 1

    if container_entry is not None:
        original = str(container_entry["original_ref"])
        resolved = str(container_entry["resolved_ref"])
        matches: list[tuple[int, re.Match[str]]] = []
        for line_index, line in enumerate(lines):
            container_match = CONTAINER_RE.match(line)
            if container_match and container_match.group("spec") in {
                original,
                resolved,
            }:
                matches.append((line_index, container_match))
        if len(matches) != 1:
            raise ContractError(f"{path}: expected one reviewed container reference")
        line_index, container_match = matches[0]
        if container_match.group("spec") == original:
            if container_match.group("tail").strip():
                raise ContractError(f"{path}: mutable container has an inline comment")
            newline = container_match.group("eol")
            lines[line_index] = (
                lines[line_index][: container_match.start("spec")]
                + resolved
                + f" # original: {original}{newline}"
            )
            changes["container_pins"] += 1
        else:
            original_comment = ORIGINAL_COMMENT_RE.fullmatch(
                container_match.group("tail")
            )
            if original_comment is None or original_comment.group("ref") != original:
                raise ContractError(f"{path}: pinned container lacks reviewed origin")

    return "".join(lines), changes


def transform_workflow(
    root: Path,
    path: Path,
    entries: dict[str, dict[str, object]],
    exceptions: dict[str, dict[str, str]],
    container_entry: dict[str, object] | None = None,
) -> tuple[str, Counter[str]]:
    return transform_content(
        root,
        path,
        path.read_text(encoding="utf-8"),
        entries,
        exceptions,
        package_workflow=True,
        container_entry=container_entry,
    )


def transform_batch_workflow(
    root: Path,
    path: Path,
    entries: dict[str, dict[str, object]],
    exceptions: dict[str, dict[str, str]],
) -> tuple[str, Counter[str]]:
    return transform_content(
        root,
        path,
        path.read_text(encoding="utf-8"),
        entries,
        exceptions,
        package_workflow=False,
    )


def apply_hardening(root: Path) -> Counter[str]:
    workflows = registered_workflows(root)
    lock = load_lock(root)
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError("could not establish the source commit") from exc
    if head != lock["source_commit"]:
        raise ContractError(
            f"hardening must start from reviewed commit {lock['source_commit']}"
        )
    entries = lock_by_original(lock)
    exceptions = permission_exceptions(lock)
    containers = container_lock_by_workflow(lock)
    transformed: dict[Path, str] = {}
    totals: Counter[str] = Counter()

    for path in workflows:
        relative = path.relative_to(root).as_posix()
        content, changes = transform_workflow(
            root, path, entries, exceptions, containers.get(relative)
        )
        transformed[path] = content
        totals.update(changes)

    for path in batch_paths(root):
        content, changes = transform_batch_workflow(root, path, entries, exceptions)
        transformed[path] = content
        totals.update(changes)

    if dict(totals) != EXPECTED_MIGRATION_CHANGES:
        raise ContractError(f"unexpected transformation counts: {dict(totals)}")

    for path, content in transformed.items():
        path.write_text(content, encoding="utf-8", newline="")
    return totals


def validate_idempotence(
    root: Path,
    workflows: list[Path],
    batches: list[Path],
    entries: dict[str, dict[str, object]],
    exceptions: dict[str, dict[str, str]],
    containers: dict[str, dict[str, object]],
) -> None:
    for path in workflows:
        relative = path.relative_to(root).as_posix()
        transformed, changes = transform_workflow(
            root, path, entries, exceptions, containers.get(relative)
        )
        if transformed != path.read_text(encoding="utf-8") or any(changes.values()):
            raise ContractError(f"{path}: hardening transform is not idempotent")
    for path in batches:
        transformed, changes = transform_batch_workflow(root, path, entries, exceptions)
        if transformed != path.read_text(encoding="utf-8") or any(changes.values()):
            raise ContractError(f"{path}: batch hardening transform is not idempotent")


def source_snapshot(
    root: Path, paths: Iterable[Path], source_commit: str
) -> dict[str, bytes]:
    relative_paths = sorted(path.relative_to(root).as_posix() for path in paths)
    try:
        archive = subprocess.run(
            ["git", "-C", str(root), "archive", source_commit, "--", *relative_paths],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError("could not read the reviewed source workflow set") from exc
    if len(archive) > MAX_SOURCE_ARCHIVE_BYTES:
        raise ContractError("reviewed source workflow archive exceeds its bound")

    expected = set(relative_paths)
    observed: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
            for member in stream.getmembers():
                if member.isdir():
                    continue
                if not member.isfile() or member.name not in expected:
                    raise ContractError("reviewed source archive is malformed")
                extracted = stream.extractfile(member)
                if extracted is None or member.name in observed:
                    raise ContractError("reviewed source archive is incomplete")
                observed[member.name] = extracted.read()
    except (tarfile.TarError, OSError) as exc:
        raise ContractError("could not parse the reviewed source archive") from exc
    if set(observed) != expected:
        raise ContractError("reviewed source archive has missing workflows")
    return observed


def validate_source_derivation(
    root: Path,
    workflows: list[Path],
    batches: list[Path],
    entries: dict[str, dict[str, object]],
    exceptions: dict[str, dict[str, str]],
    containers: dict[str, dict[str, object]],
    source_commit: str,
) -> None:
    snapshot = source_snapshot(root, [*workflows, *batches], source_commit)
    totals: Counter[str] = Counter()
    for path in workflows:
        relative = path.relative_to(root).as_posix()
        try:
            source = snapshot[relative].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError(f"{path}: source workflow is not UTF-8") from exc
        transformed, changes = transform_content(
            root,
            path,
            source,
            entries,
            exceptions,
            package_workflow=True,
            container_entry=containers.get(relative),
        )
        if transformed.encode("utf-8") != path.read_bytes():
            raise ContractError(f"{path}: change is outside the guarded transform")
        totals.update(changes)
    for path in batches:
        relative = path.relative_to(root).as_posix()
        try:
            source = snapshot[relative].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError(f"{path}: source workflow is not UTF-8") from exc
        transformed, changes = transform_content(
            root,
            path,
            source,
            entries,
            exceptions,
            package_workflow=False,
        )
        if transformed.encode("utf-8") != path.read_bytes():
            raise ContractError(f"{path}: change is outside the guarded transform")
        totals.update(changes)
    if dict(totals) != EXPECTED_MIGRATION_CHANGES:
        raise ContractError("guarded source transformation counts changed")


def _permission_values(lines: list[str], start: int) -> list[str]:
    end = _permission_block_end(lines, start)
    return [
        line.strip()
        for line in lines[start + 1 : end]
        if line.strip() and not line.strip().startswith("#")
    ]


def _validate_permissions(
    root: Path,
    path: Path,
    lines: list[str],
    exceptions: dict[str, dict[str, str]],
) -> None:
    permission_lines = [
        (index, line)
        for index, line in enumerate(lines)
        if re.match(r"^\s*permissions\s*:", line)
    ]
    root_blocks = [
        index
        for index, line in permission_lines
        if line.strip() == "permissions:" and not line.startswith((" ", "\t"))
    ]
    if len(root_blocks) != 1:
        raise ContractError(f"{path}: expected exactly one top-level permissions block")
    if _permission_values(lines, root_blocks[0]) != ["contents: read"]:
        raise ContractError(f"{path}: permissions must be exactly contents: read")

    relative = path.relative_to(root).as_posix()
    job_blocks = [
        index for index, line in permission_lines if line.startswith((" ", "\t"))
    ]
    if relative not in exceptions:
        if job_blocks:
            raise ContractError(f"{path}: undeclared job-level permissions")
        return
    if len(job_blocks) != 1:
        raise ContractError(f"{path}: expected one declared job permission exception")
    if _permission_values(lines, job_blocks[0]) != [
        "contents: read",
        "packages: read",
    ]:
        raise ContractError(f"{path}: job permission exception does not match lock")


def _validate_batch_permissions(
    root: Path,
    path: Path,
    lines: list[str],
    exceptions: dict[str, dict[str, str]],
) -> set[str]:
    permission_indexes = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^\s*permissions\s*:", line)
    ]
    root_blocks = [
        index
        for index in permission_indexes
        if not lines[index].startswith((" ", "\t"))
    ]
    if len(root_blocks) != 1 or _permission_values(lines, root_blocks[0]) != [
        "contents: read"
    ]:
        raise ContractError(f"{path}: batch root permissions are not read-only")
    start, end = _summary_job_bounds(lines, path)
    summary_blocks = [
        index
        for index in permission_indexes
        if start < index < end and lines[index].startswith("    ")
    ]
    if len(summary_blocks) != 1 or _permission_values(lines, summary_blocks[0]) != [
        "actions: read",
        "contents: read",
    ]:
        raise ContractError(f"{path}: summary permissions are not exact")
    forwarded: set[str] = set()
    package_blocks = [
        index
        for index in permission_indexes
        if index != root_blocks[0] and index not in summary_blocks
    ]
    for index in package_blocks:
        if _permission_values(lines, index) != [
            "contents: read",
            "packages: read",
        ]:
            raise ContractError(f"{path}: package call permissions are not exact")
        workflow = _batch_permission_workflow(path, lines, index)
        if workflow not in exceptions:
            raise ContractError(
                f"{path}: package call permission is absent from the reviewed lock"
            )
        if workflow in forwarded:
            raise ContractError(f"{path}: duplicate package call permission forwarding")
        forwarded.add(workflow)
    if len(permission_indexes) != 2 + len(forwarded):
        raise ContractError(f"{path}: batch contains an unreviewed permission block")
    return forwarded


def workflow_set_sha256(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def workflow_snapshot_sha256(snapshot: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(snapshot):
        path = relative.encode("utf-8")
        content = snapshot[relative]
        digest.update(len(path).to_bytes(4, "big"))
        digest.update(path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def validate_authenticated_base(
    root: Path,
    hardened_paths: list[Path],
    lock: dict[str, object],
    expected_base_commit: str,
) -> str:
    if (
        not FULL_SHA_RE.fullmatch(expected_base_commit)
        or expected_base_commit == "0" * 40
    ):
        raise ContractError("authenticated pull-request base is not a canonical SHA")
    try:
        snapshot = source_snapshot(root, hardened_paths, expected_base_commit)
    except ContractError as error:
        raise ContractError(
            "could not read the authenticated advanced pull-request base"
        ) from error
    digest = workflow_snapshot_sha256(snapshot)
    if digest == lock["hardened_workflow_sha256"]:
        return "current_hardened_snapshot"
    if digest == lock["migration_parent_workflow_sha256"]:
        return "reviewed_migration_parent"
    raise ContractError(
        "advanced pull-request base does not match the reviewed hardened "
        "workflow snapshot"
    )


def validate_hardening(
    root: Path, *, expected_base_commit: str
) -> dict[str, int | str]:
    workflows = registered_workflows(root)
    batches = batch_paths(root)
    hardened_paths = [*workflows, *batches]
    lock = load_lock(root)
    validate_authenticated_base(
        root, hardened_paths, lock, expected_base_commit
    )
    entries = lock_by_original(lock)
    exceptions = permission_exceptions(lock)
    containers = container_lock_by_workflow(lock)
    actual_originals: Counter[str] = Counter()
    external_count = 0
    checkout_count = 0
    forwarded_permission_exceptions: set[str] = set()

    for path in hardened_paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        if path in batches:
            forwarded_permission_exceptions.update(
                _validate_batch_permissions(root, path, lines, exceptions)
            )
        else:
            _validate_permissions(root, path, lines, exceptions)
        lines_with_endings = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for index, line in enumerate(lines_with_endings):
            match = USES_RE.match(line)
            if not match:
                continue
            spec = match.group("spec")
            if spec.startswith("./"):
                continue
            external_count += 1
            if spec.startswith("docker://"):
                if not DOCKER_DIGEST_RE.fullmatch(spec):
                    raise ContractError(f"{path}: mutable Docker reference: {spec}")
                continue

            action, owner_repo, _, ref = split_github_action(spec)
            if not FULL_SHA_RE.fullmatch(ref):
                raise ContractError(f"{path}: mutable GitHub action: {spec}")

            comment = ORIGINAL_COMMENT_RE.fullmatch(match.group("tail"))
            if comment is None:
                raise ContractError(
                    f"{path}: action pin lacks a reviewed origin: {spec}"
                )
            original = comment.group("ref")
            entry = entries.get(original)
            if entry is None:
                raise ContractError(
                    f"{path}: original ref absent from lock: {original}"
                )
            original_action, _, _, _ = split_github_action(original)
            if original_action != action or entry["resolved_commit"] != ref:
                raise ContractError(f"{path}: pin does not match lock: {spec}")
            actual_originals[original] += 1

            if owner_repo.lower() == "actions/checkout":
                checkout_count += 1
                if not _checkout_has_disabled_credentials(
                    lines_with_endings, index, match
                ):
                    raise ContractError(
                        f"{path}: checkout does not disable persisted credentials"
                    )

    if forwarded_permission_exceptions != set(exceptions):
        raise ContractError(
            "batch package-call permissions do not match the reviewed exceptions"
        )

    expected_originals = Counter(
        {original: int(entry["occurrences"]) for original, entry in entries.items()}
    )
    if actual_originals != expected_originals:
        raise ContractError(
            "action-lock occurrence mismatch: "
            f"expected {dict(expected_originals)}, found {dict(actual_originals)}"
        )
    if external_count != EXPECTED_EXTERNAL_USES:
        raise ContractError(
            f"expected {EXPECTED_EXTERNAL_USES} external uses, found {external_count}"
        )
    if checkout_count != EXPECTED_WORKFLOWS + EXPECTED_BATCHES:
        raise ContractError(
            "expected one checkout per package and batch workflow, "
            f"found {checkout_count}"
        )


    for relative, entry in containers.items():
        path = root / relative
        matches = [
            match
            for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
            if (match := CONTAINER_RE.match(line)) is not None
            and match.group("spec") == entry["resolved_ref"]
        ]
        if len(matches) != 1:
            raise ContractError(f"{path}: reviewed container pin is missing")
        comment = ORIGINAL_COMMENT_RE.fullmatch(matches[0].group("tail"))
        if comment is None or comment.group("ref") != entry["original_ref"]:
            raise ContractError(f"{path}: container pin lacks a reviewed origin")

    topology = exact_run.discover_topology(root)
    topology_payload = exact_run.topology_payload(topology)
    if topology_payload["mutable_external_actions"]:
        raise ContractError(
            "exact-run topology still contains mutable execution references: "
            f"{topology_payload['mutable_external_actions']}"
        )
    if topology_payload["over_capacity_batches"]:
        raise ContractError("exact-run topology contains an over-capacity batch")
    expected_refs = {
        f"{entry['original_ref'].rsplit('@', 1)[0]}@{entry['resolved_commit']}"
        for entry in entries.values()
    }
    expected_refs.update(
        f"docker://{entry['resolved_ref']}" for entry in containers.values()
    )
    observed_refs = set(topology_payload["external_actions"])
    if observed_refs != expected_refs:
        raise ContractError(
            "exact-run external dependency set does not match the reviewed lock"
        )
    topology_digest = exact_run.topology_sha256(topology)
    if topology_digest != lock.get("hardened_topology_sha256"):
        raise ContractError(
            "exact-run topology digest does not match the reviewed lock"
        )
    workflow_digest = workflow_set_sha256(root, hardened_paths)
    if workflow_digest != lock.get("hardened_workflow_sha256"):
        raise ContractError("hardened workflow digest does not match the reviewed lock")
    validate_idempotence(root, workflows, batches, entries, exceptions, containers)
    return {
        "registered_workflows": len(workflows),
        "batch_workflows": len(batches),
        "external_uses": external_count,
        "container_uses": len(containers),
        "unique_original_refs": len(actual_originals),
        "checkout_uses": checkout_count,
        "permission_exceptions": len(exceptions),
        "topology_sha256": topology_digest,
        "workflow_sha256": workflow_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the guarded mechanical hardening before validation",
    )
    parser.add_argument(
        "--expected-base-commit",
        required=True,
        help="authenticated pull-request base commit used for guarded validation",
    )
    args = parser.parse_args()
    root = repository_root()
    try:
        if args.apply:
            print(json.dumps({"applied": dict(apply_hardening(root))}, sort_keys=True))
        print(
            json.dumps(
                {
                    "validated": validate_hardening(
                        root, expected_base_commit=args.expected_base_commit
                    )
                },
                sort_keys=True,
            )
        )
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
