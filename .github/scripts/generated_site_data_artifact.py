#!/usr/bin/env python3
"""Create and restore a bounded generated-site-data review artifact."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "arm-ecosystem-generated-site-data/v1"
ARCHIVE_NAME = "generated-site-data.zip"
MANIFEST_NAME = "manifest.json"
PAYLOAD_PREFIX = "payload/"
ALLOWLIST = (
    "data/category_data.yml",
    "data/category_data_windows.yml",
    "data/recently_added_packages.yaml",
)
MAX_FILE_SIZE = 8 * 1024 * 1024
MAX_TOTAL_SIZE = 16 * 1024 * 1024
MAX_MANIFEST_SIZE = 64 * 1024
MAX_ARCHIVE_SIZE = MAX_TOTAL_SIZE + MAX_MANIFEST_SIZE + 64 * 1024

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ArtifactError(RuntimeError):
    """The generated-data artifact boundary could not be verified."""


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
        requested_metadata = path.lstat()
        if stat.S_ISLNK(requested_metadata.st_mode):
            raise ArtifactError("repository path must not be a symlink")
        repository = path.resolve(strict=True)
        metadata = repository.lstat()
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactError("repository could not be resolved") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactError("repository must be a directory")
    inside = _run_git(repository, "rev-parse", "--is-inside-work-tree").strip()
    if inside != b"true":
        raise ArtifactError("repository is not a Git worktree")
    top = Path(
        _run_git(repository, "rev-parse", "--show-toplevel")
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve(strict=True)
    if top != repository:
        raise ArtifactError("repository must identify the Git worktree root")
    return repository


def _safe_repository_path(repository: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or path.as_posix() != relative
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(ord(character) < 32 or ord(character) == 127 for character in relative)
    ):
        raise ArtifactError(f"unsafe generated-data path: {relative!r}")
    candidate = repository.joinpath(*path.parts)
    current = repository
    for part in path.parts[:-1]:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ArtifactError(
                f"generated-data parent is missing: {relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ArtifactError(
                f"generated-data parent is not a real directory: {relative}"
            )
    return candidate


def _tracked_regular_mode(repository: Path, relative: str) -> int:
    output = _run_git(repository, "ls-files", "--stage", "-z", "--", relative)
    records = [record for record in output.split(b"\0") if record]
    if len(records) != 1:
        raise ArtifactError(
            f"required path is missing or not uniquely tracked: {relative}"
        )
    try:
        metadata, encoded_path = records[0].split(b"\t", maxsplit=1)
        mode, _object_id, stage = metadata.split(b" ", maxsplit=2)
        tracked_path = encoded_path.decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactError(f"malformed Git index entry for {relative}") from exc
    if tracked_path != relative or stage != b"0" or mode not in {b"100644", b"100755"}:
        raise ArtifactError(
            f"required path is not a stage-zero tracked regular file: {relative}"
        )
    return int(mode[-3:], 8)


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


def _validate_regular_mode(current_mode: int, tracked_mode: int, relative: str) -> None:
    permissions = stat.S_IMODE(current_mode)
    if permissions & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
        raise ArtifactError(
            f"generated-data file has unsafe special mode bits: {relative}"
        )
    if bool(permissions & 0o111) != bool(tracked_mode & 0o111):
        raise ArtifactError(
            f"generated-data file executable mode differs from Git: {relative}"
        )


def _read_regular_file(repository: Path, relative: str) -> FileSnapshot:
    path = _safe_repository_path(repository, relative)
    tracked_mode = _tracked_regular_mode(repository, relative)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArtifactError(
            f"required generated-data file could not be opened: {relative}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactError(
                f"required generated-data path is not a regular file: {relative}"
            )
        if before.st_nlink != 1:
            raise ArtifactError(
                f"required generated-data file must have exactly one hard link: {relative}"
            )
        if before.st_size > MAX_FILE_SIZE:
            raise ArtifactError(
                f"generated-data file exceeds its size limit: {relative}"
            )
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
        raise ArtifactError(
            f"generated-data file disappeared while reading: {relative}"
        ) from exc
    if _stat_fingerprint(before) != _stat_fingerprint(after) or _stat_fingerprint(
        after
    ) != _stat_fingerprint(current):
        raise ArtifactError(f"generated-data file mutated while being read: {relative}")
    _validate_regular_mode(current.st_mode, tracked_mode, relative)
    data = b"".join(chunks)
    if len(data) != current.st_size:
        raise ArtifactError(
            f"generated-data file size changed while reading: {relative}"
        )
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
        raise ArtifactError(
            f"generated-data file disappeared: {snapshot.path}"
        ) from exc
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
) -> None:
    head = (
        _run_git(repository, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    )
    if head != base_sha:
        raise ArtifactError("repository HEAD does not match the expected base SHA")
    if _run_git(repository, "ls-files", "--unmerged", "-z"):
        raise ArtifactError("repository contains unmerged index entries")
    if _run_git(repository, "diff", "--cached", "--name-only", "-z", "--"):
        raise ArtifactError("repository contains staged changes")
    for relative in ALLOWLIST:
        _tracked_regular_mode(repository, relative)
        path = _safe_repository_path(repository, relative)
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise ArtifactError(
                f"required generated-data file is missing: {relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ArtifactError(
                f"required generated-data path is not a regular file: {relative}"
            )
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
    if untracked:
        raise ArtifactError(
            f"repository contains untracked paths, including ignored paths: {sorted(untracked)!r}"
        )
    if allow_generated_changes:
        outside = changed.difference(ALLOWLIST)
        if outside:
            raise ArtifactError(
                f"preprocessing changed paths outside the allowlist: {sorted(outside)!r}"
            )
    elif changed:
        raise ArtifactError(f"publication checkout is not clean: {sorted(changed)!r}")


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
        raise ArtifactError("manifest cannot be encoded canonically") from exc
    return encoded + b"\n"


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits = 0
    return info


def _manifest(base_sha: str, snapshots: Sequence[FileSnapshot]) -> dict[str, Any]:
    return {
        "base_sha": base_sha,
        "files": [
            {"path": item.path, "sha256": item.sha256, "size": item.size}
            for item in snapshots
        ],
        "schema": SCHEMA,
    }


def _write_archive(
    path: Path, manifest: bytes, snapshots: Sequence[FileSnapshot]
) -> None:
    with path.open("w+b") as raw:
        with zipfile.ZipFile(
            raw, mode="w", compression=zipfile.ZIP_STORED, strict_timestamps=True
        ) as archive:
            archive.writestr(_zip_info(MANIFEST_NAME), manifest)
            for snapshot in snapshots:
                archive.writestr(
                    _zip_info(f"{PAYLOAD_PREFIX}{snapshot.path}"), snapshot.data
                )
        raw.flush()
        os.fsync(raw.fileno())


def _prepare_output(output: Path) -> tuple[Path, Path]:
    if output.name != ARCHIVE_NAME:
        raise ArtifactError(f"artifact output must be named {ARCHIVE_NAME}")
    try:
        requested_parent_metadata = output.parent.lstat()
        if stat.S_ISLNK(requested_parent_metadata.st_mode):
            raise ArtifactError("artifact output parent must not be a symlink")
        parent = output.parent.resolve(strict=True)
        parent_metadata = parent.lstat()
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactError("artifact output directory could not be inspected") from exc
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(
        parent_metadata.st_mode
    ):
        raise ArtifactError("artifact output parent must be a real directory")
    final = parent / ARCHIVE_NAME
    if final.exists() or final.is_symlink():
        raise ArtifactError("artifact output must not already exist")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".generated-site-data-", dir=parent
    )
    os.close(descriptor)
    return final, Path(temporary_name)


def pack(repository_path: Path, output: Path, base_sha: str) -> str:
    repository = _validated_repository(repository_path)
    base_sha = _validated_sha(base_sha, "base SHA")
    _assert_repository_state(repository, base_sha, allow_generated_changes=True)
    snapshots = tuple(
        _read_regular_file(repository, relative) for relative in ALLOWLIST
    )
    if sum(item.size for item in snapshots) > MAX_TOTAL_SIZE:
        raise ArtifactError("generated-data payload exceeds its total size limit")
    manifest = _canonical_json(_manifest(base_sha, snapshots))
    if len(manifest) > MAX_MANIFEST_SIZE:
        raise ArtifactError("generated-data manifest exceeds its size limit")
    final, temporary = _prepare_output(output)
    try:
        _write_archive(temporary, manifest, snapshots)
        if temporary.stat().st_size > MAX_ARCHIVE_SIZE:
            raise ArtifactError("generated-data archive exceeds its size limit")
        for snapshot in snapshots:
            _assert_snapshot_unchanged(repository, snapshot)
        _assert_repository_state(repository, base_sha, allow_generated_changes=True)
        os.replace(temporary, final)
        raw = _read_bounded_regular_file(
            final, MAX_ARCHIVE_SIZE, "generated-data archive"
        )
        restored = _load_archive(raw, base_sha)
        expected = {snapshot.path: snapshot.data for snapshot in snapshots}
        if restored != expected:
            raise ArtifactError("generated-data archive failed self-verification")
        digest = hashlib.sha256(raw).hexdigest()
    except BaseException:
        temporary.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        raise
    return digest


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactError(f"manifest contains a duplicate key: {key}")
        result[key] = value
    return result


def _parse_manifest(raw: bytes, expected_base_sha: str) -> tuple[dict[str, Any], ...]:
    if len(raw) > MAX_MANIFEST_SIZE:
        raise ArtifactError("manifest exceeds its size limit")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ArtifactError(f"manifest contains a non-finite number: {constant}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("manifest is not safe UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != {"base_sha", "files", "schema"}:
        raise ArtifactError("manifest has an unexpected top-level structure")
    if value.get("schema") != SCHEMA:
        raise ArtifactError("manifest schema is unsupported")
    if value.get("base_sha") != expected_base_sha:
        raise ArtifactError("manifest base SHA does not match the publication checkout")
    files = value.get("files")
    if not isinstance(files, list) or len(files) != len(ALLOWLIST):
        raise ArtifactError("manifest must describe the exact generated-data allowlist")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            raise ArtifactError(f"manifest file entry {index} is malformed")
        path = item.get("path")
        digest = item.get("sha256")
        size = item.get("size")
        if not isinstance(path, str):
            raise ArtifactError(f"manifest file entry {index} has a malformed path")
        _safe_manifest_path(path)
        if path in seen:
            raise ArtifactError(f"manifest contains a duplicate file entry: {path}")
        seen.add(path)
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ArtifactError(f"manifest file entry {path} has a malformed digest")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 <= size <= MAX_FILE_SIZE
        ):
            raise ArtifactError(f"manifest file entry {path} has an invalid size")
        validated.append({"path": path, "sha256": digest, "size": size})
    if tuple(item["path"] for item in validated) != ALLOWLIST:
        raise ArtifactError(
            "manifest paths are missing, extra, duplicated, or out of order"
        )
    if sum(item["size"] for item in validated) > MAX_TOTAL_SIZE:
        raise ArtifactError("manifest payload exceeds its total size limit")
    if raw != _canonical_json(value):
        raise ArtifactError("manifest is not in canonical JSON form")
    return tuple(validated)


def _safe_manifest_path(path: str) -> None:
    parsed = PurePosixPath(path)
    if (
        path not in ALLOWLIST
        or parsed.is_absolute()
        or parsed.as_posix() != path
        or "\\" in path
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ArtifactError(f"manifest contains an unsafe or unapproved path: {path!r}")


def _validate_zip_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    parsed = PurePosixPath(name)
    if (
        not name
        or parsed.is_absolute()
        or parsed.as_posix() != name
        or "\\" in name
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ArtifactError(f"archive contains an unsafe member path: {name!r}")
    if info.flag_bits & 0x1:
        raise ArtifactError(f"archive member must not be encrypted: {name}")
    if info.compress_type != zipfile.ZIP_STORED:
        raise ArtifactError(
            f"archive member uses an unapproved compression method: {name}"
        )
    mode = info.external_attr >> 16
    if info.create_system != 3 or not stat.S_ISREG(mode) or stat.S_IMODE(mode) != 0o644:
        raise ArtifactError(f"archive member is not a canonical regular file: {name}")
    if info.date_time != _FIXED_ZIP_TIME or info.extra or info.comment:
        raise ArtifactError(f"archive member metadata is not canonical: {name}")


def _load_archive(raw: bytes, expected_base_sha: str) -> dict[str, bytes]:
    if len(raw) > MAX_ARCHIVE_SIZE:
        raise ArtifactError("generated-data archive exceeds its size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw), mode="r") as archive:
            if archive.comment:
                raise ArtifactError("archive comment is not permitted")
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ArtifactError("archive contains duplicate member names")
            expected_names = [
                MANIFEST_NAME,
                *(f"{PAYLOAD_PREFIX}{path}" for path in ALLOWLIST),
            ]
            if names != expected_names:
                raise ArtifactError(
                    "archive members are missing, extra, or out of order"
                )
            for info in infos:
                _validate_zip_member(info)
            manifest_raw = archive.read(MANIFEST_NAME)
            entries = _parse_manifest(manifest_raw, expected_base_sha)
            payloads: dict[str, bytes] = {}
            for entry in entries:
                path = entry["path"]
                payload = archive.read(f"{PAYLOAD_PREFIX}{path}")
                if len(payload) != entry["size"]:
                    raise ArtifactError(
                        f"payload size does not match its manifest: {path}"
                    )
                if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                    raise ArtifactError(
                        f"payload digest does not match its manifest: {path}"
                    )
                payloads[path] = payload
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        if isinstance(exc, ArtifactError):
            raise
        raise ArtifactError(
            "generated-data artifact is not a valid bounded ZIP"
        ) from exc
    return payloads


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


def _read_artifact_directory(directory: Path, expected_sha256: str) -> bytes:
    try:
        requested_metadata = directory.lstat()
        if stat.S_ISLNK(requested_metadata.st_mode):
            raise ArtifactError("downloaded artifact directory must not be a symlink")
        root = directory.resolve(strict=True)
        metadata = root.lstat()
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactError(
            "downloaded artifact directory could not be resolved"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ArtifactError("downloaded artifact path must be a real directory")
    try:
        entries = list(os.scandir(root))
    except OSError as exc:
        raise ArtifactError(
            "downloaded artifact directory could not be inspected"
        ) from exc
    if len(entries) != 1 or entries[0].name != ARCHIVE_NAME:
        raise ArtifactError(
            "downloaded artifact directory must contain only the expected archive"
        )
    entry = entries[0]
    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
        raise ArtifactError("downloaded artifact must be a regular file, not a symlink")
    path = Path(entry.path)
    raw = _read_bounded_regular_file(path, MAX_ARCHIVE_SIZE, "downloaded artifact")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ArtifactError(
            "downloaded artifact digest does not match the generation job"
        )
    return raw


def _stage_payloads(repository: Path, payloads: Mapping[str, bytes]) -> dict[str, Path]:
    staged: dict[str, Path] = {}
    try:
        for relative in ALLOWLIST:
            target = _safe_repository_path(repository, relative)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.generated-",
                dir=target.parent,
            )
            temporary = Path(temporary_name)
            staged[relative] = temporary
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payloads[relative])
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, _tracked_regular_mode(repository, relative))
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
    except BaseException:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        raise
    return staged


def _rollback(repository: Path, originals: Mapping[str, FileSnapshot]) -> None:
    for relative in ALLOWLIST:
        original = originals[relative]
        target = _safe_repository_path(repository, relative)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.rollback-", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(original.data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, original.mode)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def _restore_payloads(repository: Path, payloads: Mapping[str, bytes]) -> None:
    originals = {
        relative: _read_regular_file(repository, relative) for relative in ALLOWLIST
    }
    staged = _stage_payloads(repository, payloads)
    replaced = False
    try:
        for snapshot in originals.values():
            _assert_snapshot_unchanged(repository, snapshot)
        for relative in ALLOWLIST:
            for pending in ALLOWLIST:
                if pending == relative:
                    break
                current = _read_regular_file(repository, pending)
                if current.data != payloads[pending]:
                    raise ArtifactError(
                        f"restored file mutated during publication: {pending}"
                    )
            _assert_snapshot_unchanged(repository, originals[relative])
            os.replace(staged[relative], _safe_repository_path(repository, relative))
            replaced = True
        for relative in ALLOWLIST:
            restored = _read_regular_file(repository, relative)
            if restored.data != payloads[relative]:
                raise ArtifactError(f"restored payload verification failed: {relative}")
    except BaseException:
        if replaced:
            _rollback(repository, originals)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def restore(
    repository_path: Path,
    artifact_directory: Path,
    expected_base_sha: str,
    expected_archive_sha256: str,
) -> None:
    repository = _validated_repository(repository_path)
    base_sha = _validated_sha(expected_base_sha, "expected base SHA")
    archive_sha256 = _validated_sha256(
        expected_archive_sha256, "expected archive SHA-256"
    )
    _assert_repository_state(repository, base_sha, allow_generated_changes=False)
    raw = _read_artifact_directory(artifact_directory, archive_sha256)
    payloads = _load_archive(raw, base_sha)
    _assert_repository_state(repository, base_sha, allow_generated_changes=False)
    _restore_payloads(repository, payloads)
    _assert_repository_state(repository, base_sha, allow_generated_changes=True)
    for relative in ALLOWLIST:
        restored = _read_regular_file(repository, relative)
        if restored.data != payloads[relative]:
            raise ArtifactError(
                f"final restored payload verification failed: {relative}"
            )


def verify_restored(
    repository_path: Path,
    artifact_directory: Path,
    expected_base_sha: str,
    expected_archive_sha256: str,
) -> None:
    repository = _validated_repository(repository_path)
    base_sha = _validated_sha(expected_base_sha, "expected base SHA")
    archive_sha256 = _validated_sha256(
        expected_archive_sha256, "expected archive SHA-256"
    )
    _assert_repository_state(repository, base_sha, allow_generated_changes=True)
    raw = _read_artifact_directory(artifact_directory, archive_sha256)
    payloads = _load_archive(raw, base_sha)
    snapshots: list[FileSnapshot] = []
    for relative in ALLOWLIST:
        current = _read_regular_file(repository, relative)
        snapshots.append(current)
        if current.data != payloads[relative]:
            raise ArtifactError(
                f"current generated-data bytes differ from the reviewed artifact: {relative}"
            )
    for snapshot in snapshots:
        _assert_snapshot_unchanged(repository, snapshot)
    _assert_repository_state(repository, base_sha, allow_generated_changes=True)


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
    restore_parser.add_argument("--expected-archive-sha256", required=True)
    verify_parser = subparsers.add_parser(
        "verify-restored",
        help="verify current generated files against a reviewed artifact",
    )
    verify_parser.add_argument("--repository", type=Path, required=True)
    verify_parser.add_argument("--artifact-directory", type=Path, required=True)
    verify_parser.add_argument("--expected-base-sha", required=True)
    verify_parser.add_argument("--expected-archive-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "pack":
            digest = pack(arguments.repository, arguments.output, arguments.base_sha)
            print(f"base_sha={arguments.base_sha}")
            print(f"archive_sha256={digest}")
        elif arguments.command == "restore":
            restore(
                arguments.repository,
                arguments.artifact_directory,
                arguments.expected_base_sha,
                arguments.expected_archive_sha256,
            )
            print(f"base_sha={arguments.expected_base_sha}")
            print(f"archive_sha256={arguments.expected_archive_sha256}")
        else:
            verify_restored(
                arguments.repository,
                arguments.artifact_directory,
                arguments.expected_base_sha,
                arguments.expected_archive_sha256,
            )
    except ArtifactError as exc:
        print(f"generated-site-data artifact rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
