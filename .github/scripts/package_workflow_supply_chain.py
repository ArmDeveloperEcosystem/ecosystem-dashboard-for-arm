#!/usr/bin/env python3
"""Apply and validate package-workflow supply-chain controls.

The authoritative workflow set is derived only from the 22 batch wrappers.
This script intentionally has no network access; the separately reviewed lock
file records the GitHub API and git-ls-remote resolution evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable


EXPECTED_BATCHES = 22
EXPECTED_WORKFLOWS = 960
EXPECTED_EXTERNAL_USES = 1086
LOCK_NAME = "package_workflow_action_lock.json"

REGISTRATION_RE = re.compile(
    r"^\s*uses:\s*(\./\.github/workflows/test-[^\s#]+\.yml)\s*(?:#.*)?$"
)
USES_RE = re.compile(
    r"^(?P<space>\s*)(?P<dash>-\s*)?uses:\s*"
    r"(?P<spec>[^\s#]+)(?P<tail>[ \t]*(?:#.*)?)"
    r"(?P<eol>\r?\n?)$"
)
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DOCKER_DIGEST_RE = re.compile(
    r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$"
)
ORIGINAL_COMMENT_RE = re.compile(r"^\s+# original: (?P<ref>[^\s#]+)\s*$")


class ContractError(RuntimeError):
    """Raised when the package-workflow contract is not exact."""


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
        raise ContractError(f"cannot read {lock_path.relative_to(root)}: {exc}") from exc

    if lock.get("schema_version") != 1:
        raise ContractError("unsupported action lock schema")
    entries = lock.get("actions")
    if not isinstance(entries, list) or not entries:
        raise ContractError("action lock must contain a non-empty actions list")

    originals: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ContractError("action lock entries must be objects")
        original = entry.get("original_ref")
        commit = entry.get("resolved_commit")
        occurrences = entry.get("occurrences")
        if not isinstance(original, str) or original in originals:
            raise ContractError(f"invalid or duplicate original ref: {original!r}")
        if not isinstance(commit, str) or not FULL_SHA_RE.fullmatch(commit):
            raise ContractError(f"invalid resolved commit for {original}")
        if not isinstance(occurrences, int) or occurrences < 1:
            raise ContractError(f"invalid occurrence count for {original}")
        originals.add(original)
    return lock


def lock_by_original(lock: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        entry["original_ref"]: entry
        for entry in lock["actions"]  # type: ignore[index]
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


def _step_end(lines: list[str], uses_index: int, match: re.Match[str]) -> tuple[int, int]:
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
        index for index, line in enumerate(lines) if re.match(r"^on:\s*(?:#.*)?$", line.rstrip("\r\n"))
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
) -> tuple[str, Counter[str]]:
    lines = content.splitlines(keepends=True)
    changes: Counter[str] = Counter()
    changes["permission_blocks_removed"] += _remove_unneeded_job_permissions(
        root, path, lines, exceptions
    )
    changes["permissions"] += _add_root_permissions(lines, path)

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

        pinned_action, owner_repo, _, pinned_ref = split_github_action(pinned_spec)
        if owner_repo.lower() == "actions/checkout":
            added = _add_checkout_credentials_control(lines, index, match)
            changes["checkout_credentials"] += added
            index += added
        index += 1

    return "".join(lines), changes


def transform_workflow(
    root: Path,
    path: Path,
    entries: dict[str, dict[str, object]],
    exceptions: dict[str, dict[str, str]],
) -> tuple[str, Counter[str]]:
    return transform_content(
        root, path, path.read_text(encoding="utf-8"), entries, exceptions
    )


def apply_hardening(root: Path) -> Counter[str]:
    workflows = registered_workflows(root)
    lock = load_lock(root)
    entries = lock_by_original(lock)
    exceptions = permission_exceptions(lock)
    transformed: dict[Path, str] = {}
    totals: Counter[str] = Counter()

    for path in workflows:
        content, changes = transform_workflow(root, path, entries, exceptions)
        transformed[path] = content
        totals.update(changes)

    expected = {
        "permission_blocks_removed": 35,
        "permissions": EXPECTED_WORKFLOWS,
        "pinned_uses": EXPECTED_EXTERNAL_USES,
        "checkout_credentials": EXPECTED_WORKFLOWS,
    }
    if dict(totals) != expected:
        raise ContractError(f"unexpected transformation counts: {dict(totals)}")

    for path, content in transformed.items():
        path.write_text(content, encoding="utf-8", newline="")
    return totals


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
        index for index, line in permission_lines if line.strip() == "permissions:" and not line.startswith((" ", "\t"))
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


def validate_hardening(root: Path) -> dict[str, int]:
    workflows = registered_workflows(root)
    lock = load_lock(root)
    entries = lock_by_original(lock)
    exceptions = permission_exceptions(lock)
    actual_originals: Counter[str] = Counter()
    external_count = 0
    checkout_count = 0

    for path in workflows:
        lines = path.read_text(encoding="utf-8").splitlines()
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
            if comment:
                original = comment.group("ref")
                entry = entries.get(original)
                if entry is None:
                    raise ContractError(f"{path}: original ref absent from lock: {original}")
                original_action, _, _, _ = split_github_action(original)
                if original_action != action or entry["resolved_commit"] != ref:
                    raise ContractError(f"{path}: pin does not match lock: {spec}")
                actual_originals[original] += 1

            if owner_repo.lower() == "actions/checkout":
                checkout_count += 1
                if not _checkout_has_disabled_credentials(lines_with_endings, index, match):
                    raise ContractError(
                        f"{path}: checkout does not disable persisted credentials"
                    )

    expected_originals = Counter(
        {
            original: int(entry["occurrences"])
            for original, entry in entries.items()
        }
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
    if checkout_count != EXPECTED_WORKFLOWS:
        raise ContractError(
            f"expected {EXPECTED_WORKFLOWS} checkout uses, found {checkout_count}"
        )
    return {
        "registered_workflows": len(workflows),
        "external_uses": external_count,
        "unique_original_refs": len(actual_originals),
        "checkout_uses": checkout_count,
        "permission_exceptions": len(exceptions),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the guarded mechanical hardening before validation",
    )
    args = parser.parse_args()
    root = repository_root()
    try:
        if args.apply:
            print(json.dumps({"applied": dict(apply_hardening(root))}, sort_keys=True))
        print(json.dumps({"validated": validate_hardening(root)}, sort_keys=True))
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
