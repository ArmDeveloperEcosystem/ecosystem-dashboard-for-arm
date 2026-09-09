#!/usr/bin/env python3
"""Create and restore a bounded generated-test-results delivery artifact."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "arm-ecosystem-generated-test-results/v1"
ARTIFACT_NAME = "generated-test-results.json"
INDEX_PATH = "data/test-results-index.json"
RESULTS_DIRECTORY = "data/test-results"
MAX_RESULT_FILES = 2_000
MAX_FILE_SIZE = 16 * 1024 * 1024
MAX_TOTAL_SIZE = 32 * 1024 * 1024
MAX_ARTIFACT_SIZE = 48 * 1024 * 1024

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESULT_PATH_RE = re.compile(
    r"^data/test-results/[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.json$"
)


class ArtifactError(RuntimeError):
    """The generated-test-results artifact boundary could not be verified."""


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    data: bytes
    mode: int
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    links: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def _run_git(repository: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ArtifactError(f"Git command failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ArtifactError(detail or f"Git command failed: {' '.join(arguments)}")
    return completed.stdout


def _validated_sha(value: str, label: str) -> str:
    if not _SHA_RE.fullmatch(value):
        raise ArtifactError(f"{label} must be a full lowercase Git commit SHA")
    return value


def _validated_sha256(value: str, label: str) -> str:
    if not _SHA256_RE.fullmatch(value):
        raise ArtifactError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _validated_repository(path: Path) -> Path:
    try:
        requested = path.lstat()
        if stat.S_ISLNK(requested.st_mode):
            raise ArtifactError("repository path must not be a symlink")
        repository = path.resolve(strict=True)
        metadata = repository.lstat()
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactError("repository could not be resolved") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactError("repository must be a real directory")
    if _run_git(repository, "rev-parse", "--is-inside-work-tree").strip() != b"true":
        raise ArtifactError("repository is not a Git worktree")
    top = Path(
        _run_git(repository, "rev-parse", "--show-toplevel")
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve(strict=True)
    if top != repository:
        raise ArtifactError("repository must identify the Git worktree root")
    return repository


def _is_allowed_path(relative: str) -> bool:
    return relative == INDEX_PATH or _RESULT_PATH_RE.fullmatch(relative) is not None


def _safe_repository_path(repository: Path, relative: str) -> Path:
    parsed = PurePosixPath(relative)
    if (
        not _is_allowed_path(relative)
        or parsed.is_absolute()
        or parsed.as_posix() != relative
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or any(ord(character) < 32 or ord(character) == 127 for character in relative)
    ):
        raise ArtifactError(f"unsafe generated-test-results path: {relative!r}")
    current = repository
    for part in parsed.parts[:-1]:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ArtifactError(f"generated-data parent is missing: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ArtifactError(
                f"generated-data parent is not a real directory: {relative}"
            )
    return repository.joinpath(*parsed.parts)


def _stat_fingerprint(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_mode,
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_nlink,
    )


def _read_regular_file(repository: Path, relative: str) -> FileSnapshot:
    path = _safe_repository_path(repository, relative)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArtifactError(f"generated-data file could not be opened: {relative}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactError(f"generated-data path is not a regular file: {relative}")
        if before.st_nlink != 1:
            raise ArtifactError(
                f"generated-data file must have exactly one hard link: {relative}"
            )
        if stat.S_IMODE(before.st_mode) != 0o644:
            raise ArtifactError(f"generated-data file mode must be 0644: {relative}")
        if before.st_size > MAX_FILE_SIZE:
            raise ArtifactError(f"generated-data file exceeds its size limit: {relative}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_FILE_SIZE + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise ArtifactError(
                    f"generated-data file exceeds its size limit: {relative}"
                )
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        current = path.lstat()
    except OSError as exc:
        raise ArtifactError(f"generated-data file disappeared: {relative}") from exc
    if _stat_fingerprint(before) != _stat_fingerprint(after) or _stat_fingerprint(
        after
    ) != _stat_fingerprint(current):
        raise ArtifactError(f"generated-data file mutated while being read: {relative}")
    data = b"".join(chunks)
    if len(data) != current.st_size:
        raise ArtifactError(f"generated-data file changed size while reading: {relative}")
    return FileSnapshot(
        path=relative,
        data=data,
        mode=stat.S_IMODE(current.st_mode),
        device=current.st_dev,
        inode=current.st_ino,
        size=current.st_size,
        mtime_ns=current.st_mtime_ns,
        ctime_ns=current.st_ctime_ns,
        links=current.st_nlink,
    )


def _assert_snapshot_unchanged(repository: Path, snapshot: FileSnapshot) -> None:
    path = _safe_repository_path(repository, snapshot.path)
    try:
        current = path.lstat()
    except OSError as exc:
        raise ArtifactError(f"generated-data file disappeared: {snapshot.path}") from exc
    expected = (
        stat.S_IFREG | snapshot.mode,
        snapshot.device,
        snapshot.inode,
        snapshot.size,
        snapshot.mtime_ns,
        snapshot.ctime_ns,
        snapshot.links,
    )
    if _stat_fingerprint(current) != expected:
        raise ArtifactError(
            f"generated-data file mutated during the transaction: {snapshot.path}"
        )


def _discover_paths(repository: Path) -> tuple[str, ...]:
    index = _safe_repository_path(repository, INDEX_PATH)
    try:
        index_metadata = index.lstat()
    except OSError as exc:
        raise ArtifactError("generated test-results index is missing") from exc
    if stat.S_ISLNK(index_metadata.st_mode) or not stat.S_ISREG(index_metadata.st_mode):
        raise ArtifactError("generated test-results index must be a regular file")

    results_directory = repository / RESULTS_DIRECTORY
    try:
        requested = results_directory.lstat()
        if stat.S_ISLNK(requested.st_mode) or not stat.S_ISDIR(requested.st_mode):
            raise ArtifactError("test-results path must be a real directory")
        entries = list(os.scandir(results_directory))
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactError("test-results directory could not be inspected") from exc
    result_paths: list[str] = []
    for entry in entries:
        relative = f"{RESULTS_DIRECTORY}/{entry.name}"
        if (
            entry.is_symlink()
            or not entry.is_file(follow_symlinks=False)
            or not _RESULT_PATH_RE.fullmatch(relative)
        ):
            raise ArtifactError(f"unexpected test-results directory entry: {relative}")
        result_paths.append(relative)
    result_paths.sort()
    if not result_paths or len(result_paths) > MAX_RESULT_FILES:
        raise ArtifactError("test-results file count is outside the approved bounds")
    return (INDEX_PATH, *result_paths)


def _nul_paths(output: bytes, label: str) -> tuple[str, ...]:
    paths: list[str] = []
    for encoded in output.split(b"\0"):
        if not encoded:
            continue
        try:
            paths.append(encoded.decode("utf-8", errors="strict"))
        except UnicodeDecodeError as exc:
            raise ArtifactError(f"{label} contains a non-UTF-8 path") from exc
    return tuple(paths)


def _assert_repository_state(
    repository: Path,
    base_sha: str,
    *,
    allow_generated_changes: bool,
) -> tuple[str, ...]:
    head = (
        _run_git(repository, "rev-parse", "--verify", "HEAD^{commit}")
        .decode("ascii", errors="strict")
        .strip()
    )
    if head != base_sha:
        raise ArtifactError("repository HEAD does not match the expected base SHA")
    if _run_git(repository, "ls-files", "--unmerged", "-z"):
        raise ArtifactError("repository contains unmerged index entries")
    if _run_git(repository, "diff", "--cached", "--name-only", "-z", "--"):
        raise ArtifactError("repository contains staged changes")
    changed = set(
        _nul_paths(
            _run_git(
                repository,
                "diff",
                "--name-only",
                "--no-renames",
                "-z",
                "HEAD",
                "--",
            ),
            "Git diff",
        )
    )
    untracked = set(
        _nul_paths(
            _run_git(repository, "ls-files", "--others", "-z"),
            "untracked file list",
        )
    )
    candidate = changed | untracked
    if allow_generated_changes:
        outside = sorted(path for path in candidate if not _is_allowed_path(path))
        if outside:
            raise ArtifactError(
                f"generation changed paths outside the allowlist: {outside!r}"
            )
    elif candidate:
        raise ArtifactError(f"publication checkout is not clean: {sorted(candidate)!r}")
    paths = _discover_paths(repository)
    if INDEX_PATH not in set(
        _nul_paths(
            _run_git(repository, "ls-files", "-z", "--", INDEX_PATH),
            "tracked index path",
        )
    ):
        raise ArtifactError("generated test-results index must remain tracked")
    return paths


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ArtifactError("artifact cannot be encoded canonically") from exc
    return encoded + b"\n"


def _artifact_payload(base_sha: str, snapshots: Sequence[FileSnapshot]) -> dict[str, Any]:
    return {
        "base_sha": base_sha,
        "files": [
            {
                "content": base64.b64encode(snapshot.data).decode("ascii"),
                "path": snapshot.path,
                "sha256": snapshot.sha256,
                "size": snapshot.size,
            }
            for snapshot in snapshots
        ],
        "schema": SCHEMA,
    }


def _prepare_output(output: Path) -> tuple[Path, Path]:
    if output.name != ARTIFACT_NAME:
        raise ArtifactError(f"artifact output must be named {ARTIFACT_NAME}")
    try:
        requested_parent = output.parent.lstat()
        if stat.S_ISLNK(requested_parent.st_mode):
            raise ArtifactError("artifact output parent must not be a symlink")
        parent = output.parent.resolve(strict=True)
        metadata = parent.lstat()
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactError("artifact output directory could not be inspected") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactError("artifact output parent must be a real directory")
    final = parent / ARTIFACT_NAME
    if final.exists() or final.is_symlink():
        raise ArtifactError("artifact output must not already exist")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".generated-test-results-", dir=parent
    )
    os.close(descriptor)
    return final, Path(temporary_name)


def _read_bounded_regular_file(path: Path, maximum: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArtifactError(f"{label} could not be opened as a regular file") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactError(f"{label} is not a regular file")
        if before.st_nlink != 1:
            raise ArtifactError(f"{label} must have exactly one hard link")
        if before.st_size > maximum:
            raise ArtifactError(f"{label} exceeds its size limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ArtifactError(f"{label} exceeds its size limit")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        current = path.lstat()
    except OSError as exc:
        raise ArtifactError(f"{label} disappeared while being read") from exc
    if _stat_fingerprint(before) != _stat_fingerprint(after) or _stat_fingerprint(
        after
    ) != _stat_fingerprint(current):
        raise ArtifactError(f"{label} mutated while being read")
    raw = b"".join(chunks)
    if len(raw) != current.st_size:
        raise ArtifactError(f"{label} changed size while being read")
    return raw


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError(f"artifact contains a duplicate key: {key}")
        result[key] = value
    return result


def _parse_artifact(raw: bytes, expected_base_sha: str) -> dict[str, bytes]:
    if len(raw) > MAX_ARTIFACT_SIZE:
        raise ArtifactError("generated-test-results artifact exceeds its size limit")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ArtifactError(f"artifact contains a non-finite number: {constant}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("artifact is not safe UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != {"base_sha", "files", "schema"}:
        raise ArtifactError("artifact has an unexpected top-level structure")
    if value.get("schema") != SCHEMA:
        raise ArtifactError("artifact schema is unsupported")
    if value.get("base_sha") != expected_base_sha:
        raise ArtifactError("artifact base SHA does not match the publication checkout")
    files = value.get("files")
    if not isinstance(files, list) or not 2 <= len(files) <= MAX_RESULT_FILES + 1:
        raise ArtifactError("artifact file count is outside the approved bounds")
    payloads: dict[str, bytes] = {}
    total = 0
    for index, item in enumerate(files):
        if not isinstance(item, dict) or set(item) != {
            "content",
            "path",
            "sha256",
            "size",
        }:
            raise ArtifactError(f"artifact file entry {index} is malformed")
        path = item.get("path")
        digest = item.get("sha256")
        size = item.get("size")
        encoded = item.get("content")
        if not isinstance(path, str) or not _is_allowed_path(path):
            raise ArtifactError(f"artifact file entry {index} has an unsafe path")
        if path in payloads:
            raise ArtifactError(f"artifact contains a duplicate file entry: {path}")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ArtifactError(f"artifact file entry {path} has a malformed digest")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 <= size <= MAX_FILE_SIZE
        ):
            raise ArtifactError(f"artifact file entry {path} has an invalid size")
        if not isinstance(encoded, str) or len(encoded) > (MAX_FILE_SIZE * 4 // 3) + 8:
            raise ArtifactError(f"artifact file entry {path} has invalid encoded bytes")
        try:
            content = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise ArtifactError(
                f"artifact file entry {path} is not canonical base64"
            ) from exc
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise ArtifactError(f"artifact file entry {path} failed byte validation")
        payloads[path] = content
        total += len(content)
        if total > MAX_TOTAL_SIZE:
            raise ArtifactError("artifact payload exceeds its total size limit")
    paths = tuple(payloads)
    if paths != tuple(sorted(paths)) or paths[0] != INDEX_PATH:
        raise ArtifactError("artifact paths are missing, extra, or out of order")
    if raw != _canonical_json(value):
        raise ArtifactError("artifact is not in canonical JSON form")
    return payloads


def _read_artifact_directory(directory: Path, expected_sha256: str) -> bytes:
    try:
        requested = directory.lstat()
        if stat.S_ISLNK(requested.st_mode):
            raise ArtifactError("downloaded artifact directory must not be a symlink")
        root = directory.resolve(strict=True)
        metadata = root.lstat()
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactError("downloaded artifact directory could not be resolved") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactError("downloaded artifact path must be a real directory")
    try:
        entries = list(os.scandir(root))
    except OSError as exc:
        raise ArtifactError("downloaded artifact directory could not be inspected") from exc
    if len(entries) != 1 or entries[0].name != ARTIFACT_NAME:
        raise ArtifactError("downloaded artifact directory has unexpected contents")
    entry = entries[0]
    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
        raise ArtifactError("downloaded artifact must be a regular file")
    raw = _read_bounded_regular_file(
        Path(entry.path), MAX_ARTIFACT_SIZE, "downloaded artifact"
    )
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ArtifactError("downloaded artifact digest does not match generation")
    return raw


def pack(repository_path: Path, output: Path, base_sha: str) -> str:
    repository = _validated_repository(repository_path)
    base_sha = _validated_sha(base_sha, "base SHA")
    paths = _assert_repository_state(
        repository, base_sha, allow_generated_changes=True
    )
    snapshots = tuple(_read_regular_file(repository, relative) for relative in paths)
    if sum(snapshot.size for snapshot in snapshots) > MAX_TOTAL_SIZE:
        raise ArtifactError("generated-data payload exceeds its total size limit")
    raw = _canonical_json(_artifact_payload(base_sha, snapshots))
    if len(raw) > MAX_ARTIFACT_SIZE:
        raise ArtifactError("generated-test-results artifact exceeds its size limit")
    final, temporary = _prepare_output(output)
    try:
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        for snapshot in snapshots:
            _assert_snapshot_unchanged(repository, snapshot)
        if paths != _assert_repository_state(
            repository, base_sha, allow_generated_changes=True
        ):
            raise ArtifactError("generated-data path set changed during packaging")
        os.replace(temporary, final)
        verified_raw = _read_bounded_regular_file(
            final, MAX_ARTIFACT_SIZE, "generated-test-results artifact"
        )
        expected = {snapshot.path: snapshot.data for snapshot in snapshots}
        if _parse_artifact(verified_raw, base_sha) != expected:
            raise ArtifactError("generated-test-results artifact failed self-verification")
        return hashlib.sha256(verified_raw).hexdigest()
    except BaseException:
        temporary.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        raise


def _write_staged_file(target: Path, data: bytes) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.generated-", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _rewrite_exact(repository: Path, payloads: Mapping[str, bytes]) -> None:
    results_directory = repository / RESULTS_DIRECTORY
    for entry in list(os.scandir(results_directory)):
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            raise ArtifactError("cannot safely rewrite a non-regular result entry")
        relative = f"{RESULTS_DIRECTORY}/{entry.name}"
        if not _RESULT_PATH_RE.fullmatch(relative):
            raise ArtifactError("cannot safely rewrite an unexpected result entry")
        Path(entry.path).unlink()
    for relative, data in payloads.items():
        target = _safe_repository_path(repository, relative)
        staged = _write_staged_file(target, data)
        os.replace(staged, target)


def _restore_payloads(repository: Path, payloads: Mapping[str, bytes]) -> None:
    original_paths = _discover_paths(repository)
    originals = {
        relative: _read_regular_file(repository, relative) for relative in original_paths
    }
    staged: dict[str, Path] = {}
    try:
        for relative, data in payloads.items():
            staged[relative] = _write_staged_file(
                _safe_repository_path(repository, relative), data
            )
        for snapshot in originals.values():
            _assert_snapshot_unchanged(repository, snapshot)
        stale = sorted(set(originals).difference(payloads), reverse=True)
        for relative in stale:
            _assert_snapshot_unchanged(repository, originals[relative])
            _safe_repository_path(repository, relative).unlink()
        for relative in payloads:
            os.replace(staged[relative], _safe_repository_path(repository, relative))
        discovered = _discover_paths(repository)
        if discovered != tuple(payloads):
            raise ArtifactError("restored generated-data path set is not exact")
        for relative, expected in payloads.items():
            if _read_regular_file(repository, relative).data != expected:
                raise ArtifactError(f"restored payload verification failed: {relative}")
    except BaseException:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        try:
            _rewrite_exact(
                repository,
                {relative: snapshot.data for relative, snapshot in originals.items()},
            )
        except BaseException as rollback_exc:
            raise ArtifactError("generated-data restore and rollback both failed") from rollback_exc
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def restore(
    repository_path: Path,
    artifact_directory: Path,
    expected_base_sha: str,
    expected_artifact_sha256: str,
) -> None:
    repository = _validated_repository(repository_path)
    base_sha = _validated_sha(expected_base_sha, "expected base SHA")
    artifact_sha256 = _validated_sha256(
        expected_artifact_sha256, "expected artifact SHA-256"
    )
    _assert_repository_state(repository, base_sha, allow_generated_changes=False)
    raw = _read_artifact_directory(artifact_directory, artifact_sha256)
    payloads = _parse_artifact(raw, base_sha)
    _assert_repository_state(repository, base_sha, allow_generated_changes=False)
    _restore_payloads(repository, payloads)
    paths = _assert_repository_state(
        repository, base_sha, allow_generated_changes=True
    )
    if paths != tuple(payloads):
        raise ArtifactError("final restored generated-data path set is not exact")


def verify_restored(
    repository_path: Path,
    artifact_directory: Path,
    expected_base_sha: str,
    expected_artifact_sha256: str,
) -> None:
    repository = _validated_repository(repository_path)
    base_sha = _validated_sha(expected_base_sha, "expected base SHA")
    artifact_sha256 = _validated_sha256(
        expected_artifact_sha256, "expected artifact SHA-256"
    )
    paths = _assert_repository_state(
        repository, base_sha, allow_generated_changes=True
    )
    raw = _read_artifact_directory(artifact_directory, artifact_sha256)
    payloads = _parse_artifact(raw, base_sha)
    if paths != tuple(payloads):
        raise ArtifactError("current generated-data path set differs from the artifact")
    snapshots: list[FileSnapshot] = []
    for relative, expected in payloads.items():
        snapshot = _read_regular_file(repository, relative)
        snapshots.append(snapshot)
        if snapshot.data != expected:
            raise ArtifactError(
                f"current generated-data bytes differ from the artifact: {relative}"
            )
    for snapshot in snapshots:
        _assert_snapshot_unchanged(repository, snapshot)
    if paths != _assert_repository_state(
        repository, base_sha, allow_generated_changes=True
    ):
        raise ArtifactError("generated-data path set changed during verification")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    pack_parser = subparsers.add_parser("pack", help="create a deterministic artifact")
    pack_parser.add_argument("--repository", type=Path, required=True)
    pack_parser.add_argument("--output", type=Path, required=True)
    pack_parser.add_argument("--base-sha", required=True)
    restore_parser = subparsers.add_parser(
        "restore", help="validate and restore an artifact"
    )
    restore_parser.add_argument("--repository", type=Path, required=True)
    restore_parser.add_argument("--artifact-directory", type=Path, required=True)
    restore_parser.add_argument("--expected-base-sha", required=True)
    restore_parser.add_argument("--expected-artifact-sha256", required=True)
    verify_parser = subparsers.add_parser(
        "verify-restored", help="verify restored files against an artifact"
    )
    verify_parser.add_argument("--repository", type=Path, required=True)
    verify_parser.add_argument("--artifact-directory", type=Path, required=True)
    verify_parser.add_argument("--expected-base-sha", required=True)
    verify_parser.add_argument("--expected-artifact-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "pack":
            digest = pack(arguments.repository, arguments.output, arguments.base_sha)
            print(f"artifact_sha256={digest}")
        elif arguments.command == "restore":
            restore(
                arguments.repository,
                arguments.artifact_directory,
                arguments.expected_base_sha,
                arguments.expected_artifact_sha256,
            )
            print(f"artifact_sha256={arguments.expected_artifact_sha256}")
        else:
            verify_restored(
                arguments.repository,
                arguments.artifact_directory,
                arguments.expected_base_sha,
                arguments.expected_artifact_sha256,
            )
    except (ArtifactError, OSError) as exc:
        print(f"generated-test-results artifact rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
