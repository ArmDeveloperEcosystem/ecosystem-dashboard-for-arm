#!/usr/bin/env python3
"""Publish allowlisted generated data through one automation-owned review PR."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlencode, urlsplit

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PRODUCER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"
)
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,239}$")
_AUTOMATION_PREFIX = "automation/generated-data/"
_MARKER_VERSION = "v1"
_TRAILER_PRODUCER = "Generated-Data-Producer"
_TRAILER_BRANCH = "Generated-Data-Branch"
_TRAILER_BASE_BRANCH = "Generated-Data-Base-Branch"
_TRAILER_BASE_SHA = "Generated-Data-Base-SHA"


class PublishError(RuntimeError):
    """The generated-data transaction cannot proceed safely."""


@dataclass(frozen=True)
class Config:
    producer: str
    base_branch: str
    expected_base_sha: str
    head_branch: str
    title: str
    commit_message: str
    paths: tuple[str, ...]
    required_tracked_paths: tuple[str, ...]
    repository: str
    server_url: str
    run_url: str
    output_path: Path | None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> Config:
        required = {
            "producer": "GENERATED_DATA_PRODUCER",
            "base_branch": "GENERATED_DATA_BASE_BRANCH",
            "expected_base_sha": "GENERATED_DATA_EXPECTED_BASE_SHA",
            "head_branch": "GENERATED_DATA_HEAD_BRANCH",
            "title": "GENERATED_DATA_TITLE",
            "commit_message": "GENERATED_DATA_COMMIT_MESSAGE",
            "repository": "GITHUB_REPOSITORY",
        }
        values: dict[str, str] = {}
        for field, variable in required.items():
            value = environment.get(variable, "").strip()
            if not value:
                raise PublishError(f"{variable} is required")
            values[field] = value

        paths = _parse_path_list(environment.get("GENERATED_DATA_PATHS", ""))
        required_tracked_paths = _parse_path_list(
            environment.get("GENERATED_DATA_REQUIRED_TRACKED_PATHS", "")
        )
        server_url = environment.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        run_id = environment.get("GITHUB_RUN_ID", "").strip()
        run_url = (
            f"{server_url}/{values['repository']}/actions/runs/{run_id}"
            if run_id
            else f"{server_url}/{values['repository']}/actions"
        )
        output = environment.get("GITHUB_OUTPUT", "").strip()
        config = cls(
            producer=values["producer"],
            base_branch=values["base_branch"],
            expected_base_sha=values["expected_base_sha"],
            head_branch=values["head_branch"],
            title=values["title"],
            commit_message=values["commit_message"],
            paths=paths,
            required_tracked_paths=required_tracked_paths,
            repository=values["repository"],
            server_url=server_url,
            run_url=run_url,
            output_path=Path(output) if output else None,
        )
        config.validate()
        ref_name = environment.get("GITHUB_REF_NAME", "").strip()
        if ref_name and ref_name != config.base_branch:
            raise PublishError("base branch does not match GITHUB_REF_NAME")
        return config

    def validate(self) -> None:
        if not _PRODUCER_RE.fullmatch(self.producer):
            raise PublishError("producer must be a canonical lowercase slug")
        if not _SHA_RE.fullmatch(self.expected_base_sha):
            raise PublishError("expected base SHA must be a full lowercase Git commit")
        if not _REPOSITORY_RE.fullmatch(self.repository):
            raise PublishError("GITHUB_REPOSITORY is malformed")
        server = urlsplit(self.server_url)
        if (
            server.scheme != "https"
            or not server.netloc
            or server.username is not None
            or server.password is not None
            or server.path not in {"", "/"}
            or server.query
            or server.fragment
            or self.server_url.endswith("/")
        ):
            raise PublishError("GITHUB_SERVER_URL must be a canonical HTTPS origin")
        _validate_branch(self.base_branch, "base branch")
        _validate_branch(self.head_branch, "head branch")
        expected_prefix = f"{_AUTOMATION_PREFIX}{self.producer}/"
        if not self.head_branch.startswith(expected_prefix):
            raise PublishError(
                f"head branch must be under the producer namespace {expected_prefix!r}"
            )
        if self.head_branch == self.base_branch:
            raise PublishError("generated-data head branch must differ from its base")
        _validate_single_line(self.title, "title", maximum=200)
        _validate_single_line(self.commit_message, "commit message", maximum=200)
        if not self.paths:
            raise PublishError("at least one generated-data path is required")
        for path in self.paths:
            _validate_path_spec(path)
        for path in self.required_tracked_paths:
            _validate_path_spec(path)
            if path.endswith("/"):
                raise PublishError("required tracked paths must identify exact files")
            if not any(_path_matches_spec(path, spec) for spec in self.paths):
                raise PublishError(
                    f"required tracked path is outside the generated-data allowlist: {path}"
                )

    @property
    def owner(self) -> str:
        return self.repository.split("/", maxsplit=1)[0]

    @property
    def ownership_marker(self) -> str:
        return (
            "<!-- dashboard-generated-data:"
            f"{self.producer}:{self.base_branch}:{_MARKER_VERSION} -->"
        )

    @property
    def repository_url(self) -> str:
        return f"{self.server_url}/{self.repository}"


@dataclass(frozen=True)
class PublishResult:
    status: str
    pr_url: str = ""
    head_sha: str = ""


class GitHub(Protocol):
    def setup_git_auth(self) -> None: ...

    def list_open_pull_requests(self, config: Config) -> list[dict[str, Any]]: ...

    def create_pull_request(
        self,
        config: Config,
        *,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]: ...

    def update_pull_request(
        self,
        config: Config,
        pull_request: Mapping[str, Any],
        *,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]: ...

    def close_pull_request(
        self,
        config: Config,
        pull_request: Mapping[str, Any],
    ) -> dict[str, Any]: ...


class Git:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run(
        self,
        *arguments: str,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.root), *arguments],
                input=input_text,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PublishError(f"Git command failed: {exc}") from exc
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise PublishError(detail or f"Git command failed: {' '.join(arguments)}")
        return completed

    def text(self, *arguments: str) -> str:
        return self.run(*arguments).stdout.strip()


class GhClient:
    def setup_git_auth(self) -> None:
        self._run("auth", "setup-git")

    def list_open_pull_requests(self, config: Config) -> list[dict[str, Any]]:
        pull_requests: list[dict[str, Any]] = []
        for page in range(1, 11):
            query = urlencode(
                {
                    "state": "open",
                    "head": f"{config.owner}:{config.head_branch}",
                    "per_page": "100",
                    "page": str(page),
                }
            )
            payload = self._api("GET", f"repos/{config.repository}/pulls?{query}")
            if not isinstance(payload, list) or not all(
                isinstance(item, dict) for item in payload
            ):
                raise PublishError("GitHub returned a malformed pull-request collection")
            pull_requests.extend(payload)
            if len(payload) < 100:
                return pull_requests
        raise PublishError(
            "too many open pull requests use the deterministic generated-data head"
        )

    def create_pull_request(
        self,
        config: Config,
        *,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]:
        del head_sha
        payload = self._api(
            "POST",
            f"repos/{config.repository}/pulls",
            {
                "title": config.title,
                "head": config.head_branch,
                "base": config.base_branch,
                "body": body,
                "draft": True,
                "maintainer_can_modify": False,
            },
        )
        if not isinstance(payload, dict):
            raise PublishError("GitHub returned a malformed created pull request")
        return payload

    def update_pull_request(
        self,
        config: Config,
        pull_request: Mapping[str, Any],
        *,
        body: str,
        head_sha: str,
    ) -> dict[str, Any]:
        del head_sha
        number = _pull_request_number(pull_request)
        payload = self._api(
            "PATCH",
            f"repos/{config.repository}/pulls/{number}",
            {
                "title": config.title,
                "body": body,
            },
        )
        if not isinstance(payload, dict):
            raise PublishError("GitHub returned a malformed updated pull request")
        return payload

    def close_pull_request(
        self,
        config: Config,
        pull_request: Mapping[str, Any],
    ) -> dict[str, Any]:
        number = _pull_request_number(pull_request)
        payload = self._api(
            "PATCH",
            f"repos/{config.repository}/pulls/{number}",
            {"state": "closed"},
        )
        if not isinstance(payload, dict):
            raise PublishError("GitHub returned a malformed closed pull request")
        return payload

    def _api(
        self,
        method: str,
        endpoint: str,
        payload: Mapping[str, object] | None = None,
    ) -> object:
        arguments = ["api", "--method", method, endpoint]
        input_text = None
        if payload is not None:
            arguments.extend(["--input", "-"])
            input_text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        completed = self._run(*arguments, input_text=input_text)
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise PublishError("GitHub CLI returned non-JSON API output") from exc

    def _run(
        self,
        *arguments: str,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                ["gh", *arguments],
                input=input_text,
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PublishError(f"GitHub CLI command failed: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise PublishError(detail or "GitHub CLI command failed")
        return completed


def publish_generated_data(
    config: Config,
    *,
    repository_root: Path,
    github: GitHub,
) -> PublishResult:
    """Publish one exact generated-data state without writing the base branch."""

    config.validate()
    root = repository_root.expanduser().resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise PublishError("repository root must be a real directory")
    git = Git(root)
    top_level = Path(git.text("rev-parse", "--show-toplevel")).resolve(strict=True)
    if top_level != root:
        raise PublishError("publisher must run at the Git worktree root")
    for branch in (config.base_branch, config.head_branch):
        git.run("check-ref-format", "--branch", branch)
    origin_url = git.text("config", "--get", "remote.origin.url").removesuffix("/")
    if origin_url.removesuffix(".git") != config.repository_url:
        raise PublishError("Git origin does not match GITHUB_REPOSITORY")

    current_sha = git.text("rev-parse", "--verify", "HEAD^{commit}")
    if current_sha != config.expected_base_sha:
        raise PublishError("worktree HEAD does not match the reviewed generated-data base")
    if git.run("diff", "--cached", "--quiet", check=False).returncode != 0:
        raise PublishError("publisher requires an initially empty Git index")

    _verify_required_tracked_paths(git, root, config.required_tracked_paths)
    tracked_dirty, untracked = _worktree_candidate_paths(git)
    _verify_candidate_worktree(
        git,
        root,
        tracked_dirty=tracked_dirty,
        untracked=untracked,
        path_specs=config.paths,
        required_tracked_paths=config.required_tracked_paths,
    )

    _assert_remote_base_unchanged(git, config)

    open_pr = _one_owned_open_pull_request(config, github.list_open_pull_requests(config))
    remote_sha = _remote_head_sha(git, config.head_branch)
    if open_pr is not None and remote_sha is None:
        raise PublishError("automation-owned pull request has no matching remote head branch")
    if (
        open_pr is not None
        and _pull_request_head_sha(open_pr) != remote_sha
    ):
        raise PublishError("automation-owned pull request head does not match its remote branch")
    remote_trailers: dict[str, str] = {}
    if remote_sha is not None:
        remote_trailers = _verify_remote_branch_ownership(git, config, remote_sha)

    git.run("add", "-A", "--", *config.paths)
    changed_paths = _staged_paths(git)
    _verify_changed_paths(root, changed_paths, config.paths)
    _verify_index_modes(git, changed_paths)
    remaining_dirty, remaining_untracked = _worktree_candidate_paths(git)
    if remaining_dirty or remaining_untracked:
        raise PublishError(
            "generated-data candidate changed while the reviewed index was prepared"
        )

    if not changed_paths:
        _assert_remote_base_unchanged(git, config)
        open_pr = _require_same_open_pull_request_snapshot(
            config,
            expected=open_pr,
            observed=github.list_open_pull_requests(config),
        )
        if open_pr is None:
            return PublishResult(status="no_changes")
        closed = github.close_pull_request(config, open_pr)
        _validate_pull_request_ownership(config, closed, expected_state="closed")
        if _pull_request_ownership_snapshot(closed) != _pull_request_ownership_snapshot(
            open_pr
        ):
            raise PublishError(
                "GitHub closed a generated-data pull request with a changed ownership snapshot"
            )
        _wait_for_no_open_pull_request(config, github)
        _assert_remote_base_unchanged(git, config)
        return PublishResult(status="closed_stale")

    candidate_tree = git.text("write-tree")
    head_sha = ""
    pushed = False
    if remote_sha is not None:
        remote_tree = git.text("rev-parse", f"{remote_sha}^{{tree}}")
        if (
            remote_tree == candidate_tree
            and remote_trailers.get(_TRAILER_BASE_SHA) == config.expected_base_sha
            and remote_trailers.get(_TRAILER_BASE_BRANCH) == config.base_branch
        ):
            head_sha = remote_sha

    if not head_sha:
        open_pr = _require_same_open_pull_request_snapshot(
            config,
            expected=open_pr,
            observed=github.list_open_pull_requests(config),
        )
        git.run("switch", "--create", config.head_branch)
        git.run("config", "user.name", "github-actions[bot]")
        git.run(
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        )
        commit_body = _commit_body(config)
        git.run("commit", "--no-gpg-sign", "--file", "-", input_text=commit_body)
        head_sha = git.text("rev-parse", "--verify", "HEAD^{commit}")
        github.setup_git_auth()
        expected_remote = remote_sha or ""
        git.run(
            "push",
            f"--force-with-lease=refs/heads/{config.head_branch}:{expected_remote}",
            "origin",
            f"HEAD:refs/heads/{config.head_branch}",
        )
        published_sha = _remote_head_sha(git, config.head_branch)
        if published_sha != head_sha:
            raise PublishError("remote generated-data branch does not match the published commit")
        pushed = True

    _assert_remote_base_unchanged(git, config)
    open_pr = _require_same_open_pull_request_snapshot(
        config,
        expected=open_pr,
        observed=github.list_open_pull_requests(config),
    )
    body = _pull_request_body(config, head_sha=head_sha, changed_paths=changed_paths)
    if open_pr is None:
        try:
            pull_request = github.create_pull_request(
                config,
                body=body,
                head_sha=head_sha,
            )
        except PublishError:
            pull_request = _recover_created_pull_request(config, github, head_sha)
        status = "created"
    else:
        pull_request = github.update_pull_request(
            config,
            open_pr,
            body=body,
            head_sha=head_sha,
        )
        status = "updated" if pushed else "unchanged"

    verified = _wait_for_exact_pull_request(
        config,
        github,
        expected_number=_pull_request_number(pull_request),
        expected_head_sha=head_sha,
        expected_body=body,
    )
    _assert_remote_base_unchanged(git, config)
    return PublishResult(
        status=status,
        pr_url=str(verified["html_url"]),
        head_sha=head_sha,
    )


def _parse_path_list(raw: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                line.strip()
                for line in raw.splitlines()
                if line.strip()
            }
        )
    )


def _validate_branch(value: str, label: str) -> None:
    if not _BRANCH_RE.fullmatch(value) or "//" in value or value.endswith(("/", ".")):
        raise PublishError(f"{label} is not a bounded canonical branch name")


def _validate_single_line(value: str, label: str, *, maximum: int) -> None:
    if (
        not value
        or value != value.strip()
        or len(value) > maximum
        or any(character in value for character in "\x00\r\n")
    ):
        raise PublishError(f"{label} must be one bounded trimmed line")


def _validate_path_spec(value: str) -> None:
    raw = value.removesuffix("/")
    path = PurePosixPath(raw)
    if (
        not raw
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or path.is_absolute()
        or path.as_posix() != raw
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PublishError(f"generated-data path is unsafe: {value!r}")


def _staged_paths(git: Git) -> tuple[str, ...]:
    output = git.run(
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        "-z",
    ).stdout
    paths = tuple(sorted(item for item in output.split("\x00") if item))
    if len(paths) != len(set(paths)):
        raise PublishError("Git returned duplicate staged paths")
    return paths


def _verify_changed_paths(
    root: Path,
    changed_paths: Sequence[str],
    path_specs: Sequence[str],
) -> None:
    _verify_paths_allowlisted(changed_paths, path_specs)
    for value in changed_paths:
        _verify_regular_path_boundary(root, value, require_file=False)


def _verify_paths_allowlisted(
    changed_paths: Sequence[str],
    path_specs: Sequence[str],
) -> None:
    for value in changed_paths:
        _validate_path_spec(value)
        if not any(_path_matches_spec(value, spec) for spec in path_specs):
            raise PublishError(f"changed path is outside the generated-data allowlist: {value}")


def _path_matches_spec(path: str, spec: str) -> bool:
    if spec.endswith("/"):
        return path.startswith(spec) and len(path) > len(spec)
    return path == spec


def _worktree_candidate_paths(git: Git) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tracked_dirty = _nul_paths(
        git.run(
            "diff",
            "--name-only",
            "--no-renames",
            "--diff-filter=ACDMRTUXB",
            "-z",
            "--",
        ).stdout,
        description="dirty tracked",
    )
    untracked = _nul_paths(
        git.run(
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
        ).stdout,
        description="untracked",
    )
    return tracked_dirty, untracked


def _nul_paths(output: str, *, description: str) -> tuple[str, ...]:
    paths = tuple(sorted(item for item in output.split("\x00") if item))
    if len(paths) != len(set(paths)):
        raise PublishError(f"Git returned duplicate {description} paths")
    for path in paths:
        _validate_path_spec(path)
    return paths


def _verify_candidate_worktree(
    git: Git,
    root: Path,
    *,
    tracked_dirty: Sequence[str],
    untracked: Sequence[str],
    path_specs: Sequence[str],
    required_tracked_paths: Sequence[str],
) -> None:
    _verify_paths_allowlisted(tracked_dirty, path_specs)
    _verify_paths_allowlisted(untracked, path_specs)
    required = set(required_tracked_paths)
    unexpected_untracked = sorted(required.intersection(untracked))
    if unexpected_untracked:
        raise PublishError(
            "required generated-data files became untracked: "
            f"{unexpected_untracked[:3]!r}"
        )
    _verify_index_modes(git, tracked_dirty)
    for path in (*tracked_dirty, *untracked):
        _verify_regular_path_boundary(root, path, require_file=False)


def _verify_required_tracked_paths(
    git: Git,
    root: Path,
    required_paths: Sequence[str],
) -> None:
    for path in required_paths:
        entries = _index_entries(git, path)
        if len(entries) != 1:
            raise PublishError(
                f"required generated-data file is not tracked exactly once: {path}"
            )
        mode, stage, indexed_path = entries[0]
        if indexed_path != path or stage != "0" or mode not in {"100644", "100755"}:
            raise PublishError(
                f"required generated-data file is not a tracked regular file: {path}"
            )
        _verify_regular_path_boundary(root, path, require_file=True)


def _verify_index_modes(git: Git, paths: Sequence[str]) -> None:
    for path in paths:
        for mode, stage, indexed_path in _index_entries(git, path):
            if indexed_path != path or stage != "0":
                raise PublishError(f"generated-data index entry is conflicted: {path}")
            if mode not in {"100644", "100755"}:
                raise PublishError(
                    f"generated-data output must be a regular file: {path}"
                )


def _index_entries(git: Git, path: str) -> tuple[tuple[str, str, str], ...]:
    output = git.run("ls-files", "--stage", "-z", "--", path).stdout
    entries: list[tuple[str, str, str]] = []
    for record in (item for item in output.split("\x00") if item):
        metadata, separator, indexed_path = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise PublishError("Git returned a malformed index entry")
        mode, object_id, stage = fields
        if not re.fullmatch(r"[0-9a-f]{40,64}", object_id):
            raise PublishError("Git returned a malformed index object")
        entries.append((mode, stage, indexed_path))
    return tuple(entries)


def _verify_regular_path_boundary(
    root: Path,
    value: str,
    *,
    require_file: bool,
) -> None:
    _validate_path_spec(value)
    candidate = root
    parts = PurePosixPath(value).parts
    for index, part in enumerate(parts):
        candidate /= part
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            if require_file:
                raise PublishError(
                    f"required generated-data file is missing: {value}"
                )
            return
        except OSError as exc:
            raise PublishError(f"generated-data path could not be inspected: {value}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise PublishError(f"generated-data path must not use symlinks: {value}")
        if index < len(parts) - 1:
            if not stat.S_ISDIR(metadata.st_mode):
                raise PublishError(
                    f"generated-data parent must be a directory: {value}"
                )
        elif not stat.S_ISREG(metadata.st_mode):
            raise PublishError(f"generated-data output must be a regular file: {value}")


def _remote_head_sha(git: Git, branch: str) -> str | None:
    output = git.text("ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    if not output:
        return None
    lines = output.splitlines()
    if len(lines) != 1:
        raise PublishError("remote returned multiple generated-data branch heads")
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != f"refs/heads/{branch}" or not _SHA_RE.fullmatch(fields[0]):
        raise PublishError("remote returned a malformed generated-data branch head")
    return fields[0]


def _assert_remote_base_unchanged(git: Git, config: Config) -> None:
    git.run(
        "fetch",
        "--no-tags",
        "origin",
        f"+refs/heads/{config.base_branch}:refs/remotes/origin/{config.base_branch}",
    )
    remote_base_sha = git.text(
        "rev-parse",
        "--verify",
        f"refs/remotes/origin/{config.base_branch}^{{commit}}",
    )
    if remote_base_sha != config.expected_base_sha:
        raise PublishError(
            "base branch changed after generation; rerun against the new base instead of "
            "publishing stale data"
        )


def _verify_remote_branch_ownership(
    git: Git,
    config: Config,
    remote_sha: str,
) -> dict[str, str]:
    git.run("fetch", "--no-tags", "origin", f"refs/heads/{config.head_branch}")
    fetched_sha = git.text("rev-parse", "--verify", "FETCH_HEAD^{commit}")
    if fetched_sha != remote_sha:
        raise PublishError("generated-data branch changed while ownership was verified")
    message = git.run("show", "-s", "--format=%B", remote_sha).stdout
    trailers = _parse_trailers(message)
    expected = {
        _TRAILER_PRODUCER: config.producer,
        _TRAILER_BRANCH: config.head_branch,
        _TRAILER_BASE_BRANCH: config.base_branch,
    }
    if any(trailers.get(key) != value for key, value in expected.items()):
        raise PublishError(
            "refusing to replace a generated-data branch without exact automation ownership"
        )
    recorded_base_sha = trailers.get(_TRAILER_BASE_SHA, "")
    if not _SHA_RE.fullmatch(recorded_base_sha):
        raise PublishError("automation-owned branch has an invalid recorded base SHA")
    parents = git.text("show", "-s", "--format=%P", remote_sha).split()
    if parents != [recorded_base_sha]:
        raise PublishError(
            "automation-owned branch is not one generated commit on its recorded base"
        )
    remote_paths = _changed_paths_between(git, recorded_base_sha, remote_sha)
    _verify_paths_allowlisted(remote_paths, config.paths)
    return trailers


def _parse_trailers(message: str) -> dict[str, str]:
    trailers: dict[str, str] = {}
    for line in message.splitlines():
        key, separator, value = line.partition(":")
        if not separator or key not in {
            _TRAILER_PRODUCER,
            _TRAILER_BRANCH,
            _TRAILER_BASE_BRANCH,
            _TRAILER_BASE_SHA,
        }:
            continue
        cleaned = value.strip()
        if key in trailers:
            raise PublishError(f"automation commit contains duplicate trailer {key}")
        trailers[key] = cleaned
    return trailers


def _changed_paths_between(git: Git, base_sha: str, head_sha: str) -> tuple[str, ...]:
    output = git.run(
        "diff",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        "-z",
        base_sha,
        head_sha,
        "--",
    ).stdout
    paths = tuple(sorted(item for item in output.split("\x00") if item))
    if len(paths) != len(set(paths)):
        raise PublishError("Git returned duplicate changed paths")
    return paths


def _commit_body(config: Config) -> str:
    return (
        f"{config.commit_message}\n\n"
        f"{_TRAILER_PRODUCER}: {config.producer}\n"
        f"{_TRAILER_BRANCH}: {config.head_branch}\n"
        f"{_TRAILER_BASE_BRANCH}: {config.base_branch}\n"
        f"{_TRAILER_BASE_SHA}: {config.expected_base_sha}\n"
    )


def _pull_request_body(
    config: Config,
    *,
    head_sha: str,
    changed_paths: Sequence[str],
) -> str:
    rendered_paths = "\n".join(f"- `{path}`" for path in changed_paths)
    return (
        f"{config.ownership_marker}\n"
        "# Generated data review\n\n"
        "This draft contains deterministic generated-data updates. It does not merge "
        "or write the base branch directly.\n\n"
        f"- Producer: `{config.producer}`\n"
        f"- Reviewed base: `{config.base_branch}` at `{config.expected_base_sha}`\n"
        f"- Candidate commit: `{head_sha}`\n"
        f"- Source run: {config.run_url}\n\n"
        "Changed files:\n"
        f"{rendered_paths}\n\n"
        "This source run will not deploy while generated changes require review. After "
        "this draft is reviewed and merged, a clean rerun against the merged base may "
        "deploy.\n\n"
        "## External production activation blockers\n\n"
        "Repository owners must configure live required approving reviews and required "
        "checks, enforce those rules for administrators, and configure a protected "
        "production environment. The deployment workflow must not be merged or activated "
        "until owners have explicitly created and protected that environment.\n\n"
        "## Required workflow approval\n\n"
        "This pull request is created with `GITHUB_TOKEN`. An authorized repository "
        "writer must select **Approve workflows to run** before its required checks can "
        "satisfy the review gate. A separately governed GitHub App or fine-grained PAT "
        "is optional only; it is not required by this implementation. This action does "
        "not change repository rules, approve workflows, or configure an environment.\n\n"
        "Review the generated diff and all required checks before marking this PR ready.\n"
    )


def _one_owned_open_pull_request(
    config: Config,
    pull_requests: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    for pull_request in pull_requests:
        _validate_pull_request_ownership(
            config,
            pull_request,
            expected_state="open",
        )
    if len(pull_requests) > 1:
        raise PublishError("multiple open PRs use the deterministic generated-data branch")
    if not pull_requests:
        return None
    return pull_requests[0]


def _validate_pull_request_ownership(
    config: Config,
    pull_request: Mapping[str, Any],
    *,
    expected_state: str,
) -> None:
    state = str(pull_request.get("state", "")).casefold()
    if state != expected_state:
        raise PublishError(
            "deterministic generated-data PR has an unexpected lifecycle state"
        )
    head = pull_request.get("head")
    base = pull_request.get("base")
    head_repo = head.get("repo") if isinstance(head, Mapping) else None
    base_repo = base.get("repo") if isinstance(base, Mapping) else None
    if (
        not isinstance(head, Mapping)
        or head.get("ref") != config.head_branch
        or not isinstance(head_repo, Mapping)
        or str(head_repo.get("full_name", "")).casefold()
        != config.repository.casefold()
    ):
        raise PublishError(
            "deterministic generated-data PR has an unexpected head branch or repository"
        )
    if (
        not isinstance(base, Mapping)
        or base.get("ref") != config.base_branch
        or not isinstance(base_repo, Mapping)
        or str(base_repo.get("full_name", "")).casefold()
        != config.repository.casefold()
    ):
        raise PublishError(
            "deterministic generated-data PR was retargeted to an unexpected base"
        )
    body = pull_request.get("body")
    if not isinstance(body, str) or config.ownership_marker not in body:
        raise PublishError("deterministic generated-data PR is not automation-owned")
    user = pull_request.get("user")
    if not isinstance(user, Mapping) or user.get("login") != "github-actions[bot]":
        raise PublishError("deterministic generated-data PR has the wrong author")
    if pull_request.get("draft") is not True:
        raise PublishError(
            "refusing to rewrite a generated-data PR after it leaves draft review"
        )
    if _pull_request_base_sha(pull_request) != config.expected_base_sha:
        raise PublishError("generated-data PR is not bound to the exact reviewed base SHA")
    if not _SHA_RE.fullmatch(_pull_request_head_sha(pull_request)):
        raise PublishError("generated-data PR has an invalid head SHA")
    _pull_request_number(pull_request)


def _require_same_open_pull_request_snapshot(
    config: Config,
    *,
    expected: Mapping[str, Any] | None,
    observed: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    current = _one_owned_open_pull_request(config, observed)
    if expected is None:
        if current is not None:
            raise PublishError(
                "a generated-data pull request appeared during publication"
            )
        return None
    if (
        current is None
        or _pull_request_ownership_snapshot(current)
        != _pull_request_ownership_snapshot(expected)
    ):
        raise PublishError(
            "generated-data pull-request ownership snapshot changed during publication"
        )
    return current


def _wait_for_no_open_pull_request(config: Config, github: GitHub) -> None:
    for attempt in range(5):
        current = _one_owned_open_pull_request(
            config,
            github.list_open_pull_requests(config),
        )
        if current is None:
            return
        if attempt < 4:
            time.sleep(attempt + 1)
    raise PublishError(
        "obsolete generated-data PR closure was not stable; deployment remains blocked"
    )


def _pull_request_number(pull_request: Mapping[str, Any]) -> int:
    number = pull_request.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise PublishError("pull request has an invalid number")
    return number


def _pull_request_ownership_snapshot(
    pull_request: Mapping[str, Any],
) -> tuple[object, ...]:
    head = pull_request.get("head")
    base = pull_request.get("base")
    user = pull_request.get("user")
    if (
        not isinstance(head, Mapping)
        or not isinstance(base, Mapping)
        or not isinstance(user, Mapping)
    ):
        raise PublishError("pull request has a malformed ownership snapshot")
    head_repo = head.get("repo")
    base_repo = base.get("repo")
    if not isinstance(head_repo, Mapping) or not isinstance(base_repo, Mapping):
        raise PublishError("pull request has a malformed repository snapshot")
    return (
        _pull_request_number(pull_request),
        pull_request.get("title"),
        pull_request.get("body"),
        pull_request.get("draft"),
        user.get("login"),
        head.get("ref"),
        head.get("sha"),
        head_repo.get("full_name"),
        base.get("ref"),
        base.get("sha"),
        base_repo.get("full_name"),
    )


def _recover_created_pull_request(
    config: Config,
    github: GitHub,
    head_sha: str,
) -> dict[str, Any]:
    for attempt in range(5):
        if attempt:
            time.sleep(attempt)
        pull_request = _one_owned_open_pull_request(
            config,
            github.list_open_pull_requests(config),
        )
        if pull_request is not None and _pull_request_head_sha(pull_request) == head_sha:
            return dict(pull_request)
    raise PublishError("pull-request creation failed without a recoverable exact PR")


def _wait_for_exact_pull_request(
    config: Config,
    github: GitHub,
    *,
    expected_number: int,
    expected_head_sha: str,
    expected_body: str,
) -> Mapping[str, Any]:
    for attempt in range(5):
        if attempt:
            time.sleep(attempt)
        pull_request = _one_owned_open_pull_request(
            config,
            github.list_open_pull_requests(config),
        )
        if (
            pull_request is not None
            and _pull_request_number(pull_request) == expected_number
            and _pull_request_head_sha(pull_request) == expected_head_sha
            and pull_request.get("title") == config.title
            and pull_request.get("body") == expected_body
            and pull_request.get("draft") is True
            and _pull_request_base_sha(pull_request) == config.expected_base_sha
            and isinstance(pull_request.get("html_url"), str)
            and str(pull_request["html_url"]).startswith("https://")
        ):
            return pull_request
    raise PublishError("GitHub did not expose the exact generated-data PR and branch head")


def _pull_request_head_sha(pull_request: Mapping[str, Any]) -> str:
    head = pull_request.get("head")
    value = head.get("sha") if isinstance(head, Mapping) else None
    return value if isinstance(value, str) else ""


def _pull_request_base_sha(pull_request: Mapping[str, Any]) -> str:
    base = pull_request.get("base")
    value = base.get("sha") if isinstance(base, Mapping) else None
    return value if isinstance(value, str) else ""


def _write_outputs(path: Path | None, result: PublishResult) -> None:
    lines = {
        "status": result.status,
        "pr_url": result.pr_url,
        "head_sha": result.head_sha,
    }
    for key, value in lines.items():
        if any(character in value for character in "\x00\r\n"):
            raise PublishError(f"unsafe workflow output value for {key}")
    if path is not None:
        with path.open("a", encoding="utf-8") as output:
            for key, value in lines.items():
                output.write(f"{key}={value}\n")
    print(f"generated-data status: {result.status}")
    if result.pr_url:
        print(f"generated-data review PR: {result.pr_url}")


def main() -> int:
    try:
        config = Config.from_environment(os.environ)
        workspace = os.environ.get("GITHUB_WORKSPACE", "").strip()
        if not workspace:
            raise PublishError("GITHUB_WORKSPACE is required")
        result = publish_generated_data(
            config,
            repository_root=Path(workspace),
            github=GhClient(),
        )
        _write_outputs(config.output_path, result)
        return 0
    except (OSError, PublishError) as exc:
        print(f"generated-data publication failed safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
