#!/usr/bin/env python3
"""Validate the dashboard-owned package identity catalog.

The validator intentionally uses only the Python standard library so it can run
in repository CI without installing dependencies. It validates the schema 1.1
contract consumed by the package-onboarding service and binds every catalog
record to the exact package page and expected package workflow bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

CATALOG_REPOSITORY_PATH = ".github/package-identity-catalog.json"
CONTENT_ROOT = "content/linux/opensource_packages"
SCHEMA_VERSION = "1.1"
MAX_CATALOG_BYTES = 20_000_000
MAX_PACKAGE_BYTES = 2_000_000
MAX_WORKFLOW_BYTES = 2_000_000
MAX_PACKAGE_PAGES = 10_000
MAX_DIRECTORY_DEPTH = 16
MAX_DIRECTORY_ENTRIES = 20_000
MAX_REVISION_SNAPSHOT_BYTES = 512 * 1024 * 1024
MAX_REVISION_SNAPSHOT_ENTRIES = 30_050
MAX_REVISION_TREE_BYTES = 64 * 1024 * 1024
MAX_REPOSITORY_PATH_BYTES = 4_096

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GIT_OBJECT_ID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_GIT_TREE_ENTRY_RE = re.compile(
    rb"^([0-7]{6}) ([a-z]+) ([0-9a-f]{40}|[0-9a-f]{64}) +([0-9]+|-)\t(.+)$"
)
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_WORKFLOW_RE = re.compile(
    r"^\.github/workflows/test-[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.yml$"
)
_CONTROL_WORKFLOW_RE = re.compile(
    r"^test-all-packages-(?:batch[1-9][0-9]*|orchestrator|summary)\.yml$"
)
_CONTROL_SLUG_RE = re.compile(
    r"^all-packages-(?:batch[1-9][0-9]*|orchestrator|summary)$"
)
_RFC3339_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_PIP_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NPM_NAME_RE = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._-]*/[a-z0-9._-]+|[a-z0-9][a-z0-9._-]*)$"
)
_REGISTRY_KINDS = ("pip", "npm")
_DIMENSION_STATUSES = {"verified", "not_applicable", "unknown", "ambiguous"}
_EVIDENCE_SOURCE_KINDS = {
    "frontmatter_url",
    "github_api",
    "pypi_api",
    "npm_api",
    "manual_review",
    "generated_workflow",
}
_APPROVED_EVIDENCE_HOSTS = {
    "frontmatter_url": {
        "github.com",
        "npmjs.com",
        "pypi.org",
        "registry.npmjs.org",
        "www.npmjs.com",
    },
    "github_api": {"api.github.com"},
    "pypi_api": {"pypi.org"},
    "npm_api": {"registry.npmjs.org"},
}
_READ_CHUNK_BYTES = 64 * 1024
_GIT_OUTPUT_BYTES = 8_192
_GIT_TIMEOUT_SECONDS = 30
_GIT_BATCH_HEADER_BYTES = 256
_GIT_BINARY = shutil.which("git")
_SNAPSHOT_ROOTS = (
    CATALOG_REPOSITORY_PATH,
    CONTENT_ROOT,
    ".github/workflows",
)
_SNAPSHOT_ANCESTORS = frozenset(
    {
        ".github",
        "content",
        "content/linux",
    }
)
_GIT_ENVIRONMENT = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.environ.get("HOME", "/"),
    "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()),
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
}
_REQUIRED_OPEN_FLAGS = (
    "O_NOFOLLOW",
    "O_CLOEXEC",
    "O_DIRECTORY",
    "O_NONBLOCK",
)


class CatalogValidationError(ValueError):
    """Raised when a catalog cannot be trusted."""


class _RepositoryPathMissing(FileNotFoundError):
    """A repository-relative component disappeared during secure traversal."""

    def __init__(self, repository_path: str) -> None:
        self.repository_path = repository_path
        super().__init__(repository_path)


@dataclass
class _TraversalBudget:
    entries: int = 0

    def consume(self, amount: int, context: str) -> None:
        self.entries += amount
        if self.entries > MAX_DIRECTORY_ENTRIES:
            raise CatalogValidationError(
                f"repository traversal exceeds {MAX_DIRECTORY_ENTRIES} entries: {context}"
            )


class _DeadlinePipeReader:
    """Read one subprocess pipe without allowing an unbounded block."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._buffer = bytearray()
        self._selector = selectors.DefaultSelector()
        self._selector.register(stream, selectors.EVENT_READ)

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def close(self) -> None:
        self._selector.close()

    def read_line(self, *, maximum_bytes: int, deadline: float) -> bytes:
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                if newline > maximum_bytes:
                    raise CatalogValidationError(
                        "Git revision blob header exceeds its limit"
                    )
                result = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                return result
            if len(self._buffer) > maximum_bytes:
                raise CatalogValidationError(
                    "Git revision blob header exceeds its limit"
                )
            self._fill(deadline)

    def read_exact(self, size: int, *, deadline: float) -> bytes:
        while len(self._buffer) < size:
            self._fill(deadline)
        result = bytes(self._buffer[:size])
        del self._buffer[:size]
        return result

    def _fill(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CatalogValidationError("Git revision blob inspection timed out")
        events = self._selector.select(remaining)
        if not events:
            raise CatalogValidationError("Git revision blob inspection timed out")
        chunk = os.read(self._stream.fileno(), _READ_CHUNK_BYTES)
        if not chunk:
            raise CatalogValidationError("Git revision blob output ended unexpectedly")
        self._buffer.extend(chunk)


class _FilesystemSnapshot:
    """Preserve one descriptor-rooted view through final validation."""

    def __init__(self, root_fd: int) -> None:
        self._files: dict[str, os.stat_result] = {}
        self._directories: dict[
            str,
            tuple[os.stat_result, tuple[str, ...]],
        ] = {}
        self.protect_directory("", root_fd)

    def protect_file(
        self,
        repository_path: str,
        state: os.stat_result,
    ) -> None:
        _require_single_link(state, repository_path)
        previous = self._files.get(repository_path)
        if previous is not None and not _same_snapshot_state(previous, state):
            raise CatalogValidationError(
                f"protected file changed during validation: {repository_path}"
            )
        self._files.setdefault(repository_path, state)

    def protect_directory(
        self,
        repository_path: str,
        directory_fd: int,
    ) -> None:
        display_name = repository_path or "repository root"
        try:
            state = os.fstat(directory_fd)
        except OSError as exc:
            raise CatalogValidationError(
                f"could not inspect protected directory: {display_name}"
            ) from exc
        if not stat.S_ISDIR(state.st_mode):
            raise CatalogValidationError(
                f"protected path is not a directory: {display_name}"
            )
        names = _list_directory(directory_fd, display_name)
        previous = self._directories.get(repository_path)
        current = (state, names)
        if previous is not None and (
            not _same_snapshot_state(previous[0], state) or previous[1] != names
        ):
            raise CatalogValidationError(
                f"protected directory changed during validation: {display_name}"
            )
        self._directories.setdefault(repository_path, current)

    def verify(self, root_fd: int) -> None:
        for repository_path, expected in sorted(self._files.items()):
            current = _repository_entry_state(root_fd, repository_path)
            if not stat.S_ISREG(current.st_mode):
                raise CatalogValidationError(
                    f"protected file is no longer regular: {repository_path}"
                )
            _require_single_link(current, repository_path)
            if not _same_snapshot_state(expected, current):
                raise CatalogValidationError(
                    f"protected file changed before validation completed: "
                    f"{repository_path}"
                )

        ordered_directories = sorted(
            self._directories,
            key=lambda path: (len(PurePosixPath(path).parts), path),
            reverse=True,
        )
        for repository_path in ordered_directories:
            expected_state, expected_names = self._directories[repository_path]
            if repository_path:
                try:
                    context = _open_repository_directory(
                        root_fd,
                        repository_path,
                    )
                    with context as directory_fd:
                        current_state = os.fstat(directory_fd)
                        current_names = _list_directory(
                            directory_fd,
                            repository_path,
                        )
                except (_RepositoryPathMissing, OSError) as exc:
                    raise CatalogValidationError(
                        f"protected directory became unavailable: {repository_path}"
                    ) from exc
            else:
                try:
                    current_state = os.fstat(root_fd)
                except OSError as exc:
                    raise CatalogValidationError(
                        "repository root became unavailable"
                    ) from exc
                current_names = _list_directory(root_fd, "repository root")
            if (
                not _same_snapshot_state(expected_state, current_state)
                or expected_names != current_names
            ):
                display_name = repository_path or "repository root"
                raise CatalogValidationError(
                    f"protected directory changed before validation completed: "
                    f"{display_name}"
                )


def calculate_corpus_sha256(path_digests: list[tuple[str, str | None]]) -> str:
    """Return the canonical digest over page and workflow presence identities."""

    normalized = sorted(path_digests, key=lambda item: item[0])
    paths = [path for path, _ in normalized]
    if len(paths) != len(set(paths)):
        raise CatalogValidationError("package corpus paths must be unique")

    digest = hashlib.sha256()
    for path, content_sha256 in normalized:
        if not path or "\x00" in path or "\n" in path:
            raise CatalogValidationError("package corpus path is not digest-safe")
        if content_sha256 is not None and not _SHA256_RE.fullmatch(content_sha256):
            raise CatalogValidationError("package corpus content digest is invalid")
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        if content_sha256 is None:
            digest.update(b"absent")
        else:
            digest.update(b"sha256:")
            digest.update(content_sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def validate_catalog_revision(
    repository_root: Path,
    *,
    revision: str = "HEAD",
    catalog_relative_path: str = CATALOG_REPOSITORY_PATH,
) -> tuple[int, str]:
    """Validate a private snapshot of one exact Git commit."""

    if catalog_relative_path != CATALOG_REPOSITORY_PATH:
        raise CatalogValidationError(
            "immutable revision validation requires the canonical catalog path"
        )
    root = _require_git_repository_root(repository_root)
    resolved_revision = _resolve_git_revision(root, revision)
    with tempfile.TemporaryDirectory(prefix="package-catalog-revision-") as temporary:
        private_root = Path(temporary)
        private_root.chmod(0o700)
        snapshot_root = private_root / "snapshot"
        snapshot_root.mkdir(mode=0o700)
        _materialize_revision_snapshot(root, resolved_revision, snapshot_root)
        count = validate_catalog(snapshot_root, catalog_relative_path)
    return count, resolved_revision


def validate_catalog(
    repository_root: Path,
    catalog_relative_path: str = CATALOG_REPOSITORY_PATH,
) -> int:
    """Validate one catalog against the repository tree and return its record count."""

    catalog_path = _require_repository_path(
        catalog_relative_path,
        "catalog path",
        suffix=".json",
    )
    root_path = repository_root.absolute()
    with _open_repository_root(root_path) as root_fd:
        snapshot = _FilesystemSnapshot(root_fd)
        return _validate_catalog_from_fd(root_fd, catalog_path, snapshot)


def _require_git_repository_root(repository_root: Path) -> Path:
    root_path = repository_root.expanduser().absolute()
    try:
        state = os.lstat(root_path)
    except OSError as exc:
        raise CatalogValidationError("Git repository root is missing") from exc
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise CatalogValidationError("Git repository root must be a real directory")
    root = root_path.resolve(strict=True)
    top_level = _run_git_text(root, "rev-parse", "--show-toplevel")
    try:
        discovered = Path(top_level).resolve(strict=True)
    except OSError as exc:
        raise CatalogValidationError(
            "Git repository root could not be resolved"
        ) from exc
    if discovered != root:
        raise CatalogValidationError("repository-root must identify the Git top level")
    return root


def _resolve_git_revision(repository_root: Path, revision: str) -> str:
    if revision != "HEAD" and not _GIT_OBJECT_ID_RE.fullmatch(revision):
        raise CatalogValidationError(
            "revision must be HEAD or a full lowercase Git object ID"
        )
    resolved = _run_git_text(
        repository_root,
        "rev-parse",
        "--verify",
        f"{revision}^{{commit}}",
    )
    if not _GIT_OBJECT_ID_RE.fullmatch(resolved):
        raise CatalogValidationError("resolved revision is not a full Git commit ID")
    if revision != "HEAD" and resolved != revision:
        raise CatalogValidationError(
            "revision did not resolve to the requested exact commit"
        )
    return resolved


def _run_git_text(repository_root: Path, *arguments: str) -> str:
    if _GIT_BINARY is None:
        raise CatalogValidationError("Git is required for immutable catalog validation")
    try:
        result = subprocess.run(
            [_GIT_BINARY, "-C", str(repository_root), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_GIT_ENVIRONMENT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CatalogValidationError("Git revision inspection failed") from exc
    if (
        result.returncode != 0
        or len(result.stdout) > _GIT_OUTPUT_BYTES
        or len(result.stderr) > _GIT_OUTPUT_BYTES
    ):
        raise CatalogValidationError("Git revision inspection failed")
    try:
        output = result.stdout.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise CatalogValidationError("Git revision output was not ASCII") from exc
    if not output or "\n" in output or "\r" in output:
        raise CatalogValidationError("Git revision output was malformed")
    return output


def _materialize_revision_snapshot(
    repository_root: Path,
    revision: str,
    snapshot_root: Path,
) -> None:
    """Materialize exact Git blob bytes without archive attribute filters."""

    entries = _list_revision_entries(repository_root, revision)
    if not entries:
        raise CatalogValidationError("Git revision snapshot has no protected files")

    total_bytes = sum(size for _path, _object_id, size in entries)
    if total_bytes > MAX_REVISION_SNAPSHOT_BYTES:
        raise CatalogValidationError(
            "Git revision snapshot exceeds the bounded size limit"
        )

    _materialize_revision_blobs(repository_root, entries, snapshot_root)


def _list_revision_entries(
    repository_root: Path,
    revision: str,
) -> list[tuple[str, str, int]]:
    if _GIT_BINARY is None:
        raise CatalogValidationError("Git is required for immutable catalog validation")
    command = [
        _GIT_BINARY,
        "-C",
        str(repository_root),
        "ls-tree",
        "-r",
        "-z",
        "-l",
        "--full-tree",
        revision,
        "--",
        *_SNAPSHOT_ROOTS,
    ]
    tree_output = _run_git_bounded_output(
        command,
        maximum_stdout_bytes=MAX_REVISION_TREE_BYTES,
        context="Git revision tree inspection",
    )
    if not tree_output.endswith(b"\x00"):
        raise CatalogValidationError("Git revision tree output was malformed")

    entries: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for raw_entry in tree_output[:-1].split(b"\x00"):
        match = _GIT_TREE_ENTRY_RE.fullmatch(raw_entry)
        if match is None:
            raise CatalogValidationError("Git revision tree entry was malformed")
        raw_mode, raw_type, raw_object_id, raw_size, raw_path = match.groups()
        try:
            repository_path = raw_path.decode("utf-8", errors="strict")
            object_id = raw_object_id.decode("ascii", errors="strict")
            size_text = raw_size.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise CatalogValidationError(
                "Git revision tree entry was not canonically encoded"
            ) from exc
        _validate_revision_path(repository_path, seen)
        if raw_mode not in {b"100644", b"100755"} or raw_type != b"blob":
            raise CatalogValidationError(
                "Git revision snapshot contains a link or special file"
            )
        if size_text == "-":
            raise CatalogValidationError("Git revision blob size is unavailable")
        size = int(size_text)
        if size < 0 or size > _maximum_revision_file_bytes(repository_path):
            raise CatalogValidationError(
                f"Git revision blob exceeds its size limit: {repository_path}"
            )
        entries.append((repository_path, object_id, size))
        if len(entries) > MAX_REVISION_SNAPSHOT_ENTRIES:
            raise CatalogValidationError(
                "Git revision snapshot has an invalid entry count"
            )
    return entries


def _run_git_bounded_output(
    command: list[str],
    *,
    maximum_stdout_bytes: int,
    context: str,
) -> bytes:
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=_GIT_ENVIRONMENT,
        )
    except OSError as exc:
        raise CatalogValidationError(f"{context} could not be started") from exc
    assert process.stdout is not None
    assert process.stderr is not None
    stdout = bytearray()
    stderr = bytearray()
    deadline = time.monotonic() + _GIT_TIMEOUT_SECONDS
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, stdout)
            selector.register(process.stderr, selectors.EVENT_READ, stderr)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CatalogValidationError(f"{context} timed out")
                events = selector.select(remaining)
                if not events:
                    raise CatalogValidationError(f"{context} timed out")
                for key, _mask in events:
                    chunk = os.read(key.fileobj.fileno(), _READ_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    destination = key.data
                    destination.extend(chunk)
                    limit = (
                        maximum_stdout_bytes
                        if destination is stdout
                        else _GIT_OUTPUT_BYTES
                    )
                    if len(destination) > limit:
                        raise CatalogValidationError(f"{context} exceeded its limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CatalogValidationError(f"{context} timed out")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise CatalogValidationError(f"{context} timed out") from exc
        if returncode != 0 or stderr:
            raise CatalogValidationError(f"{context} failed")
        return bytes(stdout)
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        process.stdout.close()
        process.stderr.close()


def _validate_revision_path(repository_path: str, seen: set[str]) -> None:
    path = PurePosixPath(repository_path)
    if (
        not repository_path
        or "\\" in repository_path
        or any(character in repository_path for character in "\x00\r\n")
        or len(repository_path.encode("utf-8")) > MAX_REPOSITORY_PATH_BYTES
        or path.is_absolute()
        or path.as_posix() != repository_path
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(path.parts) > MAX_DIRECTORY_DEPTH + 4
    ):
        raise CatalogValidationError("Git revision snapshot contains an unsafe path")
    if repository_path in seen:
        raise CatalogValidationError("Git revision snapshot contains a duplicate path")
    if not _snapshot_path_is_allowed(repository_path):
        raise CatalogValidationError(
            "Git revision snapshot contains an unexpected path"
        )
    seen.add(repository_path)


def _maximum_revision_file_bytes(repository_path: str) -> int:
    if repository_path == CATALOG_REPOSITORY_PATH:
        return MAX_CATALOG_BYTES
    if repository_path.startswith(f"{CONTENT_ROOT}/"):
        return MAX_PACKAGE_BYTES
    if repository_path.startswith(".github/workflows/"):
        return MAX_WORKFLOW_BYTES
    raise CatalogValidationError("Git revision snapshot contains an unexpected path")


def _materialize_revision_blobs(
    repository_root: Path,
    entries: list[tuple[str, str, int]],
    snapshot_root: Path,
) -> None:
    if _GIT_BINARY is None:
        raise CatalogValidationError("Git is required for immutable catalog validation")
    deadline = time.monotonic() + _GIT_TIMEOUT_SECONDS
    with tempfile.TemporaryFile() as error_output:
        try:
            process = subprocess.Popen(
                [
                    _GIT_BINARY,
                    "-C",
                    str(repository_root),
                    "cat-file",
                    "--batch",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=error_output,
                bufsize=0,
                env=_GIT_ENVIRONMENT,
            )
        except OSError as exc:
            raise CatalogValidationError(
                "Git revision blob inspection could not be started"
            ) from exc

        assert process.stdin is not None
        assert process.stdout is not None
        reader = _DeadlinePipeReader(process.stdout)
        try:
            for repository_path, object_id, expected_size in entries:
                try:
                    process.stdin.write(f"{object_id}\n".encode("ascii"))
                    process.stdin.flush()
                except (BrokenPipeError, OSError) as exc:
                    raise CatalogValidationError(
                        "Git revision blob inspection failed"
                    ) from exc

                header = reader.read_line(
                    maximum_bytes=_GIT_BATCH_HEADER_BYTES,
                    deadline=deadline,
                )
                parts = header.split(b" ")
                if len(parts) != 3:
                    raise CatalogValidationError(
                        "Git revision blob header was malformed"
                    )
                raw_object_id, raw_type, raw_size = parts
                if (
                    raw_object_id != object_id.encode("ascii")
                    or raw_type != b"blob"
                    or not raw_size.isdigit()
                    or int(raw_size) != expected_size
                ):
                    raise CatalogValidationError(
                        "Git revision blob identity did not match the commit tree"
                    )
                payload = reader.read_exact(expected_size, deadline=deadline)
                if reader.read_exact(1, deadline=deadline) != b"\n":
                    raise CatalogValidationError(
                        "Git revision blob response was malformed"
                    )
                if (
                    _git_blob_object_id(payload, object_id_length=len(object_id))
                    != object_id
                ):
                    raise CatalogValidationError(
                        "Git revision blob hash did not match its object ID"
                    )
                _write_revision_snapshot_file(
                    snapshot_root,
                    repository_path,
                    payload,
                )

            process.stdin.close()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CatalogValidationError("Git revision blob inspection timed out")
            try:
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise CatalogValidationError(
                    "Git revision blob inspection timed out"
                ) from exc
            if (
                returncode != 0
                or reader.buffered_bytes != 0
                or process.stdout.read(1) != b""
            ):
                raise CatalogValidationError("Git revision blob inspection failed")
            error_output.seek(0, os.SEEK_END)
            error_size = error_output.tell()
            if error_size > _GIT_OUTPUT_BYTES:
                raise CatalogValidationError(
                    "Git revision blob error output exceeds its limit"
                )
            if error_size:
                raise CatalogValidationError(
                    "Git revision blob inspection produced unexpected error output"
                )
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        finally:
            reader.close()
            if not process.stdin.closed:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.stdout.close()
            except OSError:
                pass


def _write_revision_snapshot_file(
    snapshot_root: Path,
    repository_path: str,
    payload: bytes,
) -> None:
    destination = snapshot_root.joinpath(*PurePosixPath(repository_path).parts)
    try:
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(payload)
        destination.chmod(0o600)
    except OSError as exc:
        raise CatalogValidationError(
            f"Git revision snapshot could not materialize {repository_path}"
        ) from exc


def _git_blob_object_id(payload: bytes, *, object_id_length: int) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    if object_id_length == 40:
        digest = hashlib.sha1(usedforsecurity=False)
    elif object_id_length == 64:
        digest = hashlib.sha256()
    else:
        raise CatalogValidationError("Git revision object ID length is invalid")
    digest.update(header)
    digest.update(payload)
    return digest.hexdigest()


def _snapshot_path_is_allowed(path: str) -> bool:
    if path in _SNAPSHOT_ANCESTORS:
        return True
    return any(path == root or path.startswith(f"{root}/") for root in _SNAPSHOT_ROOTS)


def _validate_catalog_from_fd(
    root_fd: int,
    catalog_path: str,
    snapshot: _FilesystemSnapshot,
) -> int:
    payload, raw_text = _load_catalog(root_fd, catalog_path, snapshot)
    _require_exact_keys(payload, {"schema_version", "corpus", "records"}, "catalog")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise CatalogValidationError(
            f"catalog schema_version must be {SCHEMA_VERSION!r}"
        )

    corpus = _require_dict(payload["corpus"], "catalog.corpus")
    _require_exact_keys(
        corpus,
        {"content_root", "entry_count", "corpus_sha256"},
        "catalog.corpus",
    )
    if corpus["content_root"] != CONTENT_ROOT:
        raise CatalogValidationError(
            f"catalog.corpus.content_root must be {CONTENT_ROOT!r}"
        )
    entry_count = _require_int(corpus["entry_count"], "catalog.corpus.entry_count")
    if not 0 <= entry_count <= MAX_PACKAGE_PAGES:
        raise CatalogValidationError(
            f"catalog.corpus.entry_count must be between 0 and {MAX_PACKAGE_PAGES}"
        )
    corpus_sha256 = _require_sha256(
        corpus["corpus_sha256"],
        "catalog.corpus.corpus_sha256",
    )

    records = _require_list(payload["records"], "catalog.records")
    if entry_count != len(records):
        raise CatalogValidationError(
            "catalog.corpus.entry_count must equal the number of records"
        )

    content_files = _scan_package_pages(root_fd, snapshot)
    expected_content_paths = set(content_files)
    workflow_identities = _reject_orphan_package_workflows(
        root_fd,
        {PurePosixPath(content_path).stem for content_path in expected_content_paths},
        snapshot,
    )
    if entry_count != len(expected_content_paths):
        raise CatalogValidationError(
            "catalog must contain exactly one record per package page"
        )

    record_paths: list[str] = []
    slugs: list[str] = []
    casefolded_slugs: dict[str, str] = {}
    registry_owners: dict[tuple[str, str], str] = {}
    actual_path_digests: list[tuple[str, str | None]] = []

    for index, raw_record in enumerate(records):
        context = f"catalog.records[{index}]"
        record = _require_dict(raw_record, context)
        _require_exact_keys(
            record,
            {
                "slug",
                "content_path",
                "content_sha256",
                "workflow",
                "registries",
            },
            context,
        )
        slug = _require_string(record["slug"], f"{context}.slug", maximum=200)
        if not _SLUG_RE.fullmatch(slug):
            raise CatalogValidationError(f"{context}.slug is not a safe package slug")
        if _CONTROL_SLUG_RE.fullmatch(slug.casefold()):
            raise CatalogValidationError(
                f"{context}.slug is reserved for a dashboard control workflow"
            )
        content_path = _require_repository_path(
            record["content_path"],
            f"{context}.content_path",
            suffix=".md",
        )
        if not content_path.startswith(f"{CONTENT_ROOT}/"):
            raise CatalogValidationError(
                f"{context}.content_path must be below {CONTENT_ROOT}"
            )
        if PurePosixPath(content_path).stem != slug:
            raise CatalogValidationError(
                f"{context}.slug must match its package page filename"
            )
        content_sha256 = _require_sha256(
            record["content_sha256"],
            f"{context}.content_sha256",
        )

        if content_path not in content_files:
            raise CatalogValidationError(
                f"{context}.content_path does not identify a package page"
            )
        actual_content_sha256 = content_files[content_path]
        if content_sha256 != actual_content_sha256:
            raise CatalogValidationError(
                f"{context}.content_sha256 is stale for {content_path}"
            )

        folded_slug = slug.casefold()
        previous_slug = casefolded_slugs.setdefault(folded_slug, slug)
        if previous_slug != slug:
            raise CatalogValidationError(
                "package slugs conflict case-insensitively: "
                f"{previous_slug!r} and {slug!r}"
            )
        record_paths.append(content_path)
        slugs.append(slug)
        actual_path_digests.append((content_path, actual_content_sha256))

        workflow_path, workflow_sha256 = _validate_workflow(
            root_fd,
            record["workflow"],
            slug=slug,
            context=f"{context}.workflow",
            expected_identities=workflow_identities,
            snapshot=snapshot,
        )
        actual_path_digests.append((workflow_path, workflow_sha256))
        _validate_registries(
            record["registries"],
            content_path=content_path,
            workflow_path=workflow_path,
            workflow_sha256=workflow_sha256,
            registry_owners=registry_owners,
            context=f"{context}.registries",
        )

    if record_paths != sorted(record_paths):
        raise CatalogValidationError("catalog records must be sorted by content_path")
    if len(record_paths) != len(set(record_paths)):
        raise CatalogValidationError("catalog content paths must be unique")
    if len(slugs) != len(set(slugs)):
        raise CatalogValidationError("catalog package slugs must be unique")
    if set(record_paths) != expected_content_paths:
        missing = sorted(expected_content_paths - set(record_paths))
        extra = sorted(set(record_paths) - expected_content_paths)
        raise CatalogValidationError(
            "catalog package-page coverage is stale"
            f" (missing={missing[:3]!r}, extra={extra[:3]!r})"
        )

    actual_corpus_sha256 = calculate_corpus_sha256(actual_path_digests)
    if corpus_sha256 != actual_corpus_sha256:
        raise CatalogValidationError(
            "catalog.corpus.corpus_sha256 is stale for the package corpus"
        )

    canonical_text = (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if raw_text != canonical_text:
        raise CatalogValidationError(
            "catalog JSON must use sorted keys, two-space indentation, ASCII escaping, "
            "and one trailing newline"
        )
    snapshot.verify(root_fd)
    return len(records)


def _load_catalog(
    root_fd: int,
    catalog_path: str,
    snapshot: _FilesystemSnapshot,
) -> tuple[dict[str, Any], str]:
    try:
        raw = _read_repository_file(
            root_fd,
            catalog_path,
            display_name="catalog",
            maximum_bytes=MAX_CATALOG_BYTES,
            snapshot=snapshot,
        )
    except _RepositoryPathMissing as exc:
        raise CatalogValidationError(
            f"catalog is missing or not a regular file: {catalog_path}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CatalogValidationError("catalog must be UTF-8") from exc
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_object_keys)
    except (json.JSONDecodeError, CatalogValidationError) as exc:
        raise CatalogValidationError(f"catalog JSON is invalid: {exc}") from exc
    return _require_dict(payload, "catalog"), text


def _scan_package_pages(
    root_fd: int,
    snapshot: _FilesystemSnapshot,
) -> dict[str, str]:
    pages: dict[str, str] = {}
    budget = _TraversalBudget()
    try:
        with _open_repository_directory(
            root_fd,
            CONTENT_ROOT,
            snapshot=snapshot,
        ) as content_fd:
            _scan_package_directory(
                content_fd,
                relative_parts=(),
                pages=pages,
                budget=budget,
                snapshot=snapshot,
            )
    except _RepositoryPathMissing as exc:
        raise CatalogValidationError(
            f"package content root is missing or unsafe: {CONTENT_ROOT}"
        ) from exc
    return pages


def _scan_package_directory(
    directory_fd: int,
    *,
    relative_parts: tuple[str, ...],
    pages: dict[str, str],
    budget: _TraversalBudget,
    snapshot: _FilesystemSnapshot,
) -> None:
    if len(relative_parts) > MAX_DIRECTORY_DEPTH:
        raise CatalogValidationError(
            f"package directory depth exceeds {MAX_DIRECTORY_DEPTH}"
        )
    display_directory = PurePosixPath(CONTENT_ROOT, *relative_parts).as_posix()
    names_before = _list_directory(directory_fd, display_directory)
    budget.consume(len(names_before), display_directory)
    for name in names_before:
        entry_parts = (*relative_parts, name)
        repository_path = PurePosixPath(CONTENT_ROOT, *entry_parts).as_posix()
        entry_state = _entry_lstat(
            directory_fd,
            name,
            display_name=repository_path,
        )
        if stat.S_ISLNK(entry_state.st_mode):
            raise CatalogValidationError(
                f"package content path must not be a symbolic link: {repository_path}"
            )
        if stat.S_ISDIR(entry_state.st_mode):
            raise CatalogValidationError(
                "package content root must contain only top-level Markdown files: "
                f"{repository_path}"
            )
        if not stat.S_ISREG(entry_state.st_mode):
            raise CatalogValidationError(
                f"package page is not a regular file: {repository_path}"
            )
        if name == "_index.md" and not relative_parts:
            _payload, page_state = _read_regular_payload_at(
                directory_fd,
                name,
                display_name=f"content index {repository_path}",
                maximum_bytes=MAX_PACKAGE_BYTES,
                expected_identity=entry_state,
            )
            snapshot.protect_file(repository_path, page_state)
            continue
        if relative_parts or not name.endswith(".md"):
            raise CatalogValidationError(
                "package content path is not a canonical top-level .md page: "
                f"{repository_path}"
            )
        payload, page_state = _read_regular_payload_at(
            directory_fd,
            name,
            display_name=f"package page {repository_path}",
            maximum_bytes=MAX_PACKAGE_BYTES,
            expected_identity=entry_state,
        )
        snapshot.protect_file(repository_path, page_state)
        if len(pages) >= MAX_PACKAGE_PAGES:
            raise CatalogValidationError(
                f"package corpus exceeds {MAX_PACKAGE_PAGES} pages"
            )
        pages[repository_path] = hashlib.sha256(payload).hexdigest()

    names_after = _list_directory(directory_fd, display_directory)
    if names_before != names_after:
        raise CatalogValidationError(
            f"package directory entries changed during validation: {display_directory}"
        )


def _reject_orphan_package_workflows(
    root_fd: int,
    package_slugs: set[str],
    snapshot: _FilesystemSnapshot,
) -> dict[str, os.stat_result]:
    try:
        directory_context = _open_repository_directory(
            root_fd,
            ".github/workflows",
            snapshot=snapshot,
        )
        with directory_context as workflows_fd:
            names_before = _list_directory(
                workflows_fd,
                ".github/workflows",
            )
            if len(names_before) > MAX_DIRECTORY_ENTRIES:
                raise CatalogValidationError(
                    "workflow directory exceeds the bounded entry limit"
                )
            expected_names = {f"test-{slug}.yml" for slug in package_slugs}
            orphans: list[str] = []
            candidate_states: dict[str, os.stat_result] = {}
            for name in names_before:
                if not (name.endswith(".yml") or name.endswith(".yaml")):
                    continue
                repository_path = f".github/workflows/{name}"
                workflow_state = _entry_lstat(
                    workflows_fd,
                    name,
                    display_name=repository_path,
                )
                if stat.S_ISLNK(workflow_state.st_mode):
                    raise CatalogValidationError(
                        f"workflow must not be a symbolic link: {repository_path}"
                    )
                if not stat.S_ISREG(workflow_state.st_mode):
                    raise CatalogValidationError(
                        f"workflow is not a regular file: {repository_path}"
                    )
                snapshot.protect_file(repository_path, workflow_state)
                if not name.startswith("test-"):
                    continue
                candidate_states[name] = workflow_state
                if _CONTROL_WORKFLOW_RE.fullmatch(name):
                    continue
                if name not in expected_names:
                    orphans.append(repository_path)

            for name, expected_state in candidate_states.items():
                _verify_entry_identity(
                    workflows_fd,
                    name,
                    expected_state,
                    display_name=f".github/workflows/{name}",
                    operation="during workflow inventory",
                )
            names_after = _list_directory(
                workflows_fd,
                ".github/workflows",
            )
            if names_before != names_after:
                raise CatalogValidationError(
                    "workflow directory entries changed during validation"
                )
    except _RepositoryPathMissing as exc:
        if exc.repository_path == ".github/workflows":
            return {}
        raise CatalogValidationError(
            "workflow root has a missing or unsafe ancestor"
        ) from exc

    if orphans:
        raise CatalogValidationError(
            f"orphan package workflows have no exact package page: {orphans[:3]!r}"
        )
    return {
        f".github/workflows/{name}": state for name, state in candidate_states.items()
    }


def _validate_workflow(
    root_fd: int,
    raw_workflow: object,
    *,
    slug: str,
    context: str,
    expected_identities: dict[str, os.stat_result],
    snapshot: _FilesystemSnapshot,
) -> tuple[str, str | None]:
    workflow = _require_dict(raw_workflow, context)
    _require_exact_keys(workflow, {"path", "presence", "sha256"}, context)
    workflow_path = _require_repository_path(
        workflow["path"],
        f"{context}.path",
        suffix=".yml",
    )
    expected_path = f".github/workflows/test-{slug}.yml"
    if workflow_path != expected_path or not _WORKFLOW_RE.fullmatch(workflow_path):
        raise CatalogValidationError(
            f"{context}.path must be the canonical workflow path {expected_path!r}"
        )
    presence = _require_string(
        workflow["presence"],
        f"{context}.presence",
        maximum=16,
    )
    if presence not in {"present", "absent"}:
        raise CatalogValidationError(f"{context}.presence must be present or absent")

    if presence == "present":
        expected_sha256 = _require_sha256(
            workflow["sha256"],
            f"{context}.sha256",
        )
        expected_identity = expected_identities.get(workflow_path)
        if expected_identity is None:
            raise CatalogValidationError(
                f"{context} declares a workflow absent from the secure inventory"
            )
        try:
            payload = _read_repository_file(
                root_fd,
                workflow_path,
                display_name=f"package workflow {workflow_path}",
                maximum_bytes=MAX_WORKFLOW_BYTES,
                expected_identity=expected_identity,
                snapshot=snapshot,
            )
        except _RepositoryPathMissing as exc:
            raise CatalogValidationError(
                f"{context} declares a workflow that is missing or unsafe"
            ) from exc
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if expected_sha256 != actual_sha256:
            raise CatalogValidationError(
                f"{context}.sha256 is stale for {workflow_path}"
            )
        return workflow_path, actual_sha256

    if workflow["sha256"] is not None:
        raise CatalogValidationError(
            f"{context}.sha256 must be null when the workflow is absent"
        )
    if _repository_path_exists(root_fd, workflow_path):
        raise CatalogValidationError(
            f"{context} declares an existing workflow as absent"
        )
    return workflow_path, None


def _validate_registries(
    raw_registries: object,
    *,
    content_path: str,
    workflow_path: str,
    workflow_sha256: str | None,
    registry_owners: dict[tuple[str, str], str],
    context: str,
) -> None:
    registries = _require_dict(raw_registries, context)
    _require_exact_keys(registries, set(_REGISTRY_KINDS), context)
    for registry_kind in _REGISTRY_KINDS:
        dimension_context = f"{context}.{registry_kind}"
        dimension = _require_dict(registries[registry_kind], dimension_context)
        _require_exact_keys(
            dimension,
            {"status", "exhaustive", "identities", "evidence"},
            dimension_context,
        )
        status = _require_string(
            dimension["status"],
            f"{dimension_context}.status",
            maximum=32,
        )
        if status not in _DIMENSION_STATUSES:
            raise CatalogValidationError(f"{dimension_context}.status is not supported")
        exhaustive = _require_bool(
            dimension["exhaustive"],
            f"{dimension_context}.exhaustive",
        )
        identities = _require_list(
            dimension["identities"],
            f"{dimension_context}.identities",
        )
        if len(identities) > 16:
            raise CatalogValidationError(
                f"{dimension_context}.identities exceeds 16 entries"
            )
        normalized_identities: list[str] = []
        for identity_index, raw_identity in enumerate(identities):
            identity_context = f"{dimension_context}.identities[{identity_index}]"
            identity = _require_string(
                raw_identity,
                identity_context,
                maximum=214,
            )
            normalized = _normalize_registry_identity(registry_kind, identity)
            if identity != normalized:
                raise CatalogValidationError(
                    f"{identity_context} must use {registry_kind} normalization"
                )
            normalized_identities.append(identity)
        if normalized_identities != sorted(set(normalized_identities)):
            raise CatalogValidationError(
                f"{dimension_context}.identities must be sorted and unique"
            )

        evidence = _require_list(
            dimension["evidence"],
            f"{dimension_context}.evidence",
        )
        if not 1 <= len(evidence) <= 32:
            raise CatalogValidationError(
                f"{dimension_context}.evidence must contain 1 to 32 records"
            )
        evidence_kinds: set[str] = set()
        evidence_rationales: list[str] = []
        canonical_evidence: list[str] = []
        for evidence_index, raw_evidence in enumerate(evidence):
            evidence_context = f"{dimension_context}.evidence[{evidence_index}]"
            source_kind, rationale = _validate_evidence(
                raw_evidence,
                context=evidence_context,
                workflow_path=workflow_path,
                workflow_sha256=workflow_sha256,
            )
            evidence_kinds.add(source_kind)
            if rationale is not None:
                evidence_rationales.append(rationale)
            canonical_evidence.append(
                json.dumps(
                    raw_evidence,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        if canonical_evidence != sorted(canonical_evidence):
            raise CatalogValidationError(
                f"{dimension_context}.evidence must be sorted canonically"
            )

        if status == "verified" and not normalized_identities:
            raise CatalogValidationError(
                f"{dimension_context} verified status requires an identity"
            )
        if status in {"not_applicable", "unknown"} and normalized_identities:
            raise CatalogValidationError(
                f"{dimension_context} {status} status cannot claim identities"
            )
        needs_rationale = status in {"not_applicable", "unknown", "ambiguous"}
        if needs_rationale and not evidence_rationales:
            raise CatalogValidationError(
                f"{dimension_context} {status} status requires a rationale"
            )
        if status == "not_applicable" and not exhaustive:
            raise CatalogValidationError(
                f"{dimension_context} not_applicable status must be exhaustive"
            )
        if status in {"unknown", "ambiguous"} and exhaustive:
            raise CatalogValidationError(
                f"{dimension_context} {status} status cannot be exhaustive"
            )
        independent_sources = (
            {"manual_review", "pypi_api"}
            if registry_kind == "pip"
            else {"manual_review", "npm_api"}
        )
        if exhaustive and not evidence_kinds.intersection(independent_sources):
            raise CatalogValidationError(
                f"{dimension_context} exhaustive coverage requires registry or "
                "manual-review evidence"
            )

        for identity in normalized_identities:
            key = (registry_kind, identity)
            previous_owner = registry_owners.setdefault(key, content_path)
            if previous_owner != content_path:
                raise CatalogValidationError(
                    f"registry identity {registry_kind}:{identity} conflicts between "
                    f"{previous_owner} and {content_path}"
                )


def _validate_evidence(
    raw_evidence: object,
    *,
    context: str,
    workflow_path: str,
    workflow_sha256: str | None,
) -> tuple[str, str | None]:
    evidence = _require_dict(raw_evidence, context)
    _require_exact_keys(
        evidence,
        {
            "source_kind",
            "source_locator",
            "source_revision",
            "evidence_sha256",
            "verified_by",
            "verified_at",
            "rationale",
        },
        context,
    )
    source_kind = _require_string(
        evidence["source_kind"],
        f"{context}.source_kind",
        maximum=32,
    )
    if source_kind not in _EVIDENCE_SOURCE_KINDS:
        raise CatalogValidationError(f"{context}.source_kind is not supported")
    source_locator = _require_single_line(
        evidence["source_locator"],
        f"{context}.source_locator",
        maximum=2_000,
    )
    source_revision = _require_single_line(
        evidence["source_revision"],
        f"{context}.source_revision",
        maximum=256,
    )
    if source_revision in {"0" * 40, "0" * 64}:
        raise CatalogValidationError(
            f"{context}.source_revision must not be an all-zero object ID"
        )
    evidence_sha256 = _require_sha256(
        evidence["evidence_sha256"],
        f"{context}.evidence_sha256",
    )
    if evidence_sha256 == "0" * 64:
        raise CatalogValidationError(
            f"{context}.evidence_sha256 must not be the zero digest"
        )
    _require_single_line(
        evidence["verified_by"],
        f"{context}.verified_by",
        maximum=256,
    )
    verified_at = _require_single_line(
        evidence["verified_at"],
        f"{context}.verified_at",
        maximum=64,
    )
    _validate_timestamp(verified_at, f"{context}.verified_at")
    rationale_raw = evidence["rationale"]
    rationale = (
        None
        if rationale_raw is None
        else _require_single_line(
            rationale_raw,
            f"{context}.rationale",
            maximum=2_000,
        )
    )

    if source_kind == "generated_workflow":
        if not _WORKFLOW_RE.fullmatch(source_locator):
            raise CatalogValidationError(
                f"{context}.source_locator must be a package workflow path"
            )
        if not _GIT_SHA_RE.fullmatch(source_revision):
            raise CatalogValidationError(
                f"{context}.source_revision must be an immutable 40-character "
                "lowercase Git commit ID"
            )
        if source_locator != workflow_path or evidence_sha256 != workflow_sha256:
            raise CatalogValidationError(
                f"{context} must match the record workflow path and SHA-256"
            )
    elif source_kind == "manual_review":
        _validate_manual_locator(source_locator, f"{context}.source_locator")
        if not _GIT_OBJECT_ID_RE.fullmatch(source_revision):
            raise CatalogValidationError(
                f"{context}.source_revision must be an immutable 40- or "
                "64-character lowercase Git/content ID"
            )
        if rationale is None:
            raise CatalogValidationError(
                f"{context} manual-review evidence requires a rationale"
            )
    else:
        _validate_https_locator(
            source_locator,
            approved_hosts=_APPROVED_EVIDENCE_HOSTS[source_kind],
            context=f"{context}.source_locator",
        )
        if source_kind == "github_api":
            if not _GIT_OBJECT_ID_RE.fullmatch(source_revision):
                raise CatalogValidationError(
                    f"{context}.source_revision must be an immutable 40- or "
                    "64-character lowercase Git object ID"
                )
        elif not _SHA256_RE.fullmatch(source_revision):
            raise CatalogValidationError(
                f"{context}.source_revision must be an immutable lowercase "
                "SHA-256 snapshot revision"
            )
    return source_kind, rationale


def _validate_manual_locator(locator: str, context: str) -> None:
    if locator.startswith("https://"):
        _validate_https_locator(
            locator,
            approved_hosts={"github.com"},
            context=context,
        )
        return
    path_text, separator, fragment = locator.partition("#")
    _require_repository_path(path_text, context)
    if separator and (
        not fragment or any(character in fragment for character in "\x00\r\n#")
    ):
        raise CatalogValidationError(f"{context} has an invalid fragment")


def _validate_https_locator(
    locator: str,
    *,
    approved_hosts: set[str],
    context: str,
) -> None:
    try:
        parsed = urlsplit(locator)
        port = parsed.port
    except ValueError as exc:
        raise CatalogValidationError(f"{context} is not a valid URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in approved_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or not parsed.path
    ):
        raise CatalogValidationError(
            f"{context} must use an approved HTTPS evidence locator"
        )


def _validate_timestamp(value: str, context: str) -> None:
    if not _RFC3339_TIMESTAMP_RE.fullmatch(value):
        raise CatalogValidationError(
            f"{context} must use canonical RFC3339 timestamp text"
        )
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        timestamp = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise CatalogValidationError(f"{context} is not an ISO-8601 timestamp") from exc
    if timestamp.utcoffset() is None:
        raise CatalogValidationError(f"{context} must include a timezone")
    if timestamp.astimezone(UTC) > datetime.now(UTC):
        raise CatalogValidationError(f"{context} must not be in the future")


def _normalize_registry_identity(registry_kind: str, value: str) -> str:
    if registry_kind == "pip":
        normalized = re.sub(r"[-_.]+", "-", value).casefold()
        if not _PIP_NAME_RE.fullmatch(normalized):
            raise CatalogValidationError("pip package identity is invalid")
        return normalized
    normalized = value.casefold()
    package_component = normalized.rsplit("/", maxsplit=1)[-1]
    if (
        len(normalized) > 214
        or package_component in {".", ".."}
        or not _NPM_NAME_RE.fullmatch(normalized)
    ):
        raise CatalogValidationError("npm package identity is invalid")
    return normalized


def _require_descriptor_platform() -> None:
    missing_flags = [name for name in _REQUIRED_OPEN_FLAGS if not hasattr(os, name)]
    unsupported_functions = (
        os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
        or os.stat not in os.supports_follow_symlinks
        or os.listdir not in os.supports_fd
    )
    if missing_flags or unsupported_functions:
        raise CatalogValidationError(
            "descriptor-safe repository traversal is unsupported on this platform"
        )


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _file_open_flags() -> int:
    return os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC


@contextmanager
def _open_repository_root(root_path: Path) -> Iterator[int]:
    _require_descriptor_platform()
    try:
        path_state = os.lstat(root_path)
    except OSError as exc:
        raise CatalogValidationError(
            "repository root is missing or inaccessible"
        ) from exc
    if stat.S_ISLNK(path_state.st_mode):
        raise CatalogValidationError("repository root must not be a symbolic link")
    if not stat.S_ISDIR(path_state.st_mode):
        raise CatalogValidationError("repository root is not a directory")

    try:
        root_fd = os.open(root_path, _directory_open_flags())
    except OSError as exc:
        raise CatalogValidationError(
            "repository root could not be opened without following links"
        ) from exc
    try:
        opened_state = os.fstat(root_fd)
    except OSError as exc:
        os.close(root_fd)
        raise CatalogValidationError(
            "repository root descriptor could not be inspected"
        ) from exc
    if not _same_object_identity(path_state, opened_state):
        os.close(root_fd)
        raise CatalogValidationError(
            "repository root pathname was replaced while being opened"
        )

    try:
        yield root_fd
        try:
            current_state = os.lstat(root_path)
        except OSError as exc:
            raise CatalogValidationError(
                "repository root pathname changed during validation"
            ) from exc
        if stat.S_ISLNK(current_state.st_mode) or not _same_object_identity(
            opened_state, current_state
        ):
            raise CatalogValidationError(
                "repository root pathname changed during validation"
            )
    finally:
        os.close(root_fd)


@contextmanager
def _open_repository_directory(
    root_fd: int,
    repository_path: str,
    *,
    snapshot: _FilesystemSnapshot | None = None,
) -> Iterator[int]:
    parts = PurePosixPath(repository_path).parts
    with ExitStack() as stack:
        current_fd = root_fd
        traversed: list[str] = []
        for part in parts:
            traversed.append(part)
            display_name = PurePosixPath(*traversed).as_posix()
            current_fd = stack.enter_context(
                _open_directory_component(
                    current_fd,
                    part,
                    display_name=display_name,
                )
            )
            if snapshot is not None:
                snapshot.protect_directory(display_name, current_fd)
        yield current_fd


@contextmanager
def _open_directory_component(
    parent_fd: int,
    name: str,
    *,
    display_name: str,
    expected_identity: os.stat_result | None = None,
) -> Iterator[int]:
    try:
        directory_fd = os.open(
            name,
            _directory_open_flags(),
            dir_fd=parent_fd,
        )
    except FileNotFoundError as exc:
        raise _RepositoryPathMissing(display_name) from exc
    except OSError as exc:
        raise CatalogValidationError(
            f"directory path has a symbolic-link or unsafe component: {display_name}"
        ) from exc

    try:
        try:
            opened_state = os.fstat(directory_fd)
        except OSError as exc:
            raise CatalogValidationError(
                f"repository directory descriptor could not be inspected: "
                f"{display_name}"
            ) from exc
        if not stat.S_ISDIR(opened_state.st_mode):
            raise CatalogValidationError(
                f"repository directory is not a directory: {display_name}"
            )
        if expected_identity is not None and not _same_object_identity(
            expected_identity, opened_state
        ):
            raise CatalogValidationError(
                f"{display_name} pathname was replaced before traversal"
            )
        _verify_entry_identity(
            parent_fd,
            name,
            opened_state,
            display_name=display_name,
            operation="while opening the directory",
        )
        yield directory_fd
        _verify_entry_identity(
            parent_fd,
            name,
            opened_state,
            display_name=display_name,
            operation="during directory traversal",
        )
    finally:
        os.close(directory_fd)


def _read_repository_file(
    root_fd: int,
    repository_path: str,
    *,
    display_name: str,
    maximum_bytes: int,
    expected_identity: os.stat_result | None = None,
    snapshot: _FilesystemSnapshot | None = None,
) -> bytes:
    path = PurePosixPath(repository_path)
    parent_path = PurePosixPath(*path.parts[:-1]).as_posix()
    with _open_repository_directory(
        root_fd,
        parent_path,
        snapshot=snapshot,
    ) as parent_fd:
        payload, file_state = _read_regular_payload_at(
            parent_fd,
            path.name,
            display_name=display_name,
            maximum_bytes=maximum_bytes,
            expected_identity=expected_identity,
        )
    if snapshot is not None:
        snapshot.protect_file(repository_path, file_state)
    return payload


def _read_regular_payload_at(
    parent_fd: int,
    name: str,
    *,
    display_name: str,
    maximum_bytes: int,
    expected_identity: os.stat_result | None = None,
) -> tuple[bytes, os.stat_result]:
    try:
        file_fd = os.open(name, _file_open_flags(), dir_fd=parent_fd)
    except FileNotFoundError as exc:
        raise _RepositoryPathMissing(display_name) from exc
    except OSError as exc:
        raise CatalogValidationError(
            f"{display_name} has a symbolic-link or unsafe pathname"
        ) from exc

    try:
        try:
            before = os.fstat(file_fd)
        except OSError as exc:
            raise CatalogValidationError(
                f"{display_name} descriptor could not be inspected"
            ) from exc
        if not stat.S_ISREG(before.st_mode):
            raise CatalogValidationError(f"{display_name} is not a regular file")
        _require_single_link(before, display_name)
        if expected_identity is not None and not _same_object_identity(
            expected_identity, before
        ):
            raise CatalogValidationError(
                f"{display_name} pathname was replaced before it was read"
            )
        if before.st_size < 1 or before.st_size > maximum_bytes:
            raise CatalogValidationError(
                f"{display_name} size is outside the accepted bounds"
            )
        _verify_entry_identity(
            parent_fd,
            name,
            before,
            display_name=display_name,
            operation="before the descriptor read",
        )

        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = maximum_bytes + 1 - total
            if remaining <= 0:
                raise CatalogValidationError(
                    f"{display_name} size is outside the accepted bounds"
                )
            try:
                chunk = os.read(
                    file_fd,
                    min(_READ_CHUNK_BYTES, remaining),
                )
            except InterruptedError:
                continue
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum_bytes:
                raise CatalogValidationError(
                    f"{display_name} size is outside the accepted bounds"
                )

        try:
            after = os.fstat(file_fd)
        except OSError as exc:
            raise CatalogValidationError(
                f"{display_name} descriptor could not be re-inspected"
            ) from exc
        _verify_entry_identity(
            parent_fd,
            name,
            after,
            display_name=display_name,
            operation="while being read",
        )
        if not _same_file_state(before, after) or total != after.st_size:
            raise CatalogValidationError(f"{display_name} changed while being read")
        return b"".join(chunks), after
    finally:
        os.close(file_fd)


def _repository_path_exists(root_fd: int, repository_path: str) -> bool:
    path = PurePosixPath(repository_path)
    parent_path = PurePosixPath(*path.parts[:-1]).as_posix()
    try:
        with _open_repository_directory(root_fd, parent_path) as parent_fd:
            try:
                state = os.stat(
                    path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise CatalogValidationError(
                    f"could not inspect repository path: {repository_path}"
                ) from exc
            if stat.S_ISLNK(state.st_mode):
                raise CatalogValidationError(
                    f"repository path must not be a symbolic link: {repository_path}"
                )
            return True
    except _RepositoryPathMissing:
        return False


def _repository_entry_state(
    root_fd: int,
    repository_path: str,
) -> os.stat_result:
    path = PurePosixPath(repository_path)
    parent_path = PurePosixPath(*path.parts[:-1]).as_posix()
    try:
        with _open_repository_directory(root_fd, parent_path) as parent_fd:
            return _entry_lstat(
                parent_fd,
                path.name,
                display_name=repository_path,
            )
    except _RepositoryPathMissing as exc:
        raise CatalogValidationError(
            f"protected path disappeared during validation: {repository_path}"
        ) from exc


def _list_directory(directory_fd: int, display_name: str) -> tuple[str, ...]:
    try:
        names = os.listdir(directory_fd)
    except (OSError, TypeError) as exc:
        raise CatalogValidationError(
            f"could not enumerate repository directory: {display_name}"
        ) from exc
    if any(
        not isinstance(name, str) or not name or "/" in name or "\x00" in name
        for name in names
    ):
        raise CatalogValidationError(
            f"repository directory returned an unsafe entry: {display_name}"
        )
    return tuple(sorted(names))


def _entry_lstat(
    parent_fd: int,
    name: str,
    *,
    display_name: str,
) -> os.stat_result:
    try:
        return os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError as exc:
        raise CatalogValidationError(
            f"repository path disappeared during validation: {display_name}"
        ) from exc
    except OSError as exc:
        raise CatalogValidationError(
            f"could not inspect repository path: {display_name}"
        ) from exc


def _verify_entry_identity(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    *,
    display_name: str,
    operation: str,
) -> None:
    try:
        current = os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise CatalogValidationError(
            f"{display_name} pathname changed {operation}"
        ) from exc
    if stat.S_ISLNK(current.st_mode):
        raise CatalogValidationError(
            f"{display_name} became a symbolic link {operation}"
        )
    if not _same_object_identity(expected, current):
        raise CatalogValidationError(
            f"{display_name} pathname was replaced {operation}"
        )


def _same_object_identity(
    left: os.stat_result,
    right: os.stat_result,
) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
    )


def _same_snapshot_state(
    before: os.stat_result,
    after: os.stat_result,
) -> bool:
    return (
        _same_object_identity(before, after)
        and before.st_mode == after.st_mode
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
        and before.st_nlink == after.st_nlink
    )


def _require_single_link(state: os.stat_result, display_name: str) -> None:
    if state.st_nlink != 1:
        raise CatalogValidationError(
            f"protected file must have exactly one hard link: {display_name}"
        )


def _same_file_state(
    before: os.stat_result,
    after: os.stat_result,
) -> bool:
    if (
        not _same_object_identity(before, after)
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
        or before.st_nlink != after.st_nlink
    ):
        return False
    return True


def _require_repository_path(
    value: object,
    context: str,
    *,
    suffix: str | None = None,
) -> str:
    path_text = _require_string(value, context, maximum=2_000)
    path = PurePosixPath(path_text)
    if (
        "\\" in path_text
        or path.is_absolute()
        or path.as_posix() != path_text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise CatalogValidationError(
            f"{context} must be a canonical repository-relative path"
        )
    if suffix is not None and path.suffix != suffix:
        raise CatalogValidationError(f"{context} must end in {suffix}")
    return path_text


def _require_exact_keys(
    payload: dict[str, Any],
    expected: set[str],
    context: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise CatalogValidationError(
            f"{context} fields are invalid (missing={missing!r}, extra={extra!r})"
        )


def _require_dict(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogValidationError(f"{context} must be an object")
    return value


def _require_list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise CatalogValidationError(f"{context} must be an array")
    return value


def _require_string(
    value: object,
    context: str,
    *,
    maximum: int,
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CatalogValidationError(
            f"{context} must be a non-empty string of at most {maximum} characters"
        )
    return value


def _require_single_line(
    value: object,
    context: str,
    *,
    maximum: int,
) -> str:
    text = _require_string(value, context, maximum=maximum)
    if text != text.strip() or any(character in text for character in "\x00\r\n"):
        raise CatalogValidationError(f"{context} must be trimmed and single-line")
    return text


def _require_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CatalogValidationError(f"{context} must be an integer")
    return value


def _require_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise CatalogValidationError(f"{context} must be a boolean")
    return value


def _require_sha256(value: object, context: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise CatalogValidationError(f"{context} must be a lowercase SHA-256 value")
    return value


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise CatalogValidationError(f"duplicate JSON object key: {key}")
        payload[key] = value
    return payload


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the dashboard package identity catalog",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path("."),
        help="Dashboard repository root (default: current directory)",
    )
    parser.add_argument(
        "--revision",
        default="HEAD",
        help="Exact full Git commit ID to validate, or HEAD (default: HEAD)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        count, revision = validate_catalog_revision(
            args.repository_root,
            revision=args.revision,
        )
    except CatalogValidationError as exc:
        print(f"package identity catalog validation failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"validated {count} package identity catalog records "
        f"against schema {SCHEMA_VERSION} at {revision}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
