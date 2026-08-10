#!/usr/bin/env python3
"""Verify the action lock against independent, live GitHub evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIRECTORY))
import package_workflow_supply_chain as supply_chain  # noqa: E402


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CommandRunner = Callable[[Sequence[str]], str]


class OnlineEvidenceError(RuntimeError):
    """Raised when live evidence does not exactly match the reviewed lock."""


def _is_object_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(FULL_SHA_RE.fullmatch(value))
        and value != "0" * 40
    )


def _require_object(value: object, description: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise OnlineEvidenceError(f"{description} must be a JSON object")
    return value


def _verification_from_api(commit: Mapping[str, Any]) -> dict[str, object]:
    commit_details = _require_object(commit.get("commit"), "commit details")
    verification = _require_object(
        commit_details.get("verification"), "commit verification"
    )
    verified = verification.get("verified")
    reason = verification.get("reason")
    signature = verification.get("signature")
    payload = verification.get("payload")
    if not isinstance(verified, bool) or not isinstance(reason, str) or not reason:
        raise OnlineEvidenceError("commit verification is missing or malformed")
    if signature is not None and not isinstance(signature, str):
        raise OnlineEvidenceError("commit verification signature is malformed")
    if payload is not None and not isinstance(payload, str):
        raise OnlineEvidenceError("commit verification payload is malformed")
    return {
        "verified": verified,
        "reason": reason,
        "signature_present": bool(signature),
        "payload_present": bool(payload),
    }


def parse_ls_remote(output: str) -> dict[str, str]:
    """Parse ls-remote output, rejecting malformed or duplicate refs."""
    if not isinstance(output, str) or not output.strip():
        raise OnlineEvidenceError("git ls-remote returned no evidence")
    refs: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or not _is_object_id(fields[0]):
            raise OnlineEvidenceError("git ls-remote evidence is malformed")
        sha, ref = fields
        if not ref.startswith("refs/") or ref in refs:
            raise OnlineEvidenceError("git ls-remote contains an invalid duplicate ref")
        refs[ref] = sha
    return refs


def ref_query_names(requested_ref: str) -> tuple[str, str, str]:
    if (
        not isinstance(requested_ref, str)
        or not requested_ref
        or requested_ref.startswith("-")
        or any(character.isspace() for character in requested_ref)
    ):
        raise OnlineEvidenceError("requested ref is malformed")
    head_name = f"refs/heads/{requested_ref}"
    tag_name = f"refs/tags/{requested_ref}"
    return head_name, tag_name, f"{tag_name}^{{}}"


def validate_live_action_evidence(
    entry: object,
    repository_payload: object,
    commit_payload: object,
    contents_payload: object,
    ls_remote_output: str,
    tag_payload: object | None = None,
) -> None:
    """Validate one lock entry using supplied live-evidence payloads only."""
    try:
        _, commit_sha = supply_chain.validate_action_lock_entry(entry)
    except supply_chain.ContractError as error:
        raise OnlineEvidenceError(str(error)) from error
    assert isinstance(entry, dict)
    original_ref = entry["original_ref"]
    repository = entry["repository"]
    if not _is_object_id(commit_sha):
        raise OnlineEvidenceError(f"locked commit is not a Git object ID: {original_ref}")

    repository_data = _require_object(repository_payload, "repository evidence")
    if (
        repository_data.get("id") != entry["repository_id"]
        or repository_data.get("full_name") != repository
    ):
        raise OnlineEvidenceError(
            f"live repository identity contradicts {original_ref}"
        )

    commit_data = _require_object(commit_payload, "commit evidence")
    if commit_data.get("sha") != commit_sha:
        raise OnlineEvidenceError(f"live commit identity contradicts {original_ref}")
    live_verification = _verification_from_api(commit_data)
    if live_verification != entry["github_commit_verification"]:
        raise OnlineEvidenceError(
            f"live commit verification contradicts {original_ref}"
        )

    contents_data = _require_object(contents_payload, "action file evidence")
    contents_sha = contents_data.get("sha")
    if (
        contents_data.get("type") != "file"
        or contents_data.get("path") != entry["action_file"]
        or not _is_object_id(contents_sha)
    ):
        raise OnlineEvidenceError(f"live action file evidence contradicts {original_ref}")

    refs = parse_ls_remote(ls_remote_output)
    head_name, tag_name, peeled_name = ref_query_names(entry["requested_ref"])
    ref_type = entry["ref_type"]
    if ref_type == "branch":
        required_refs = {head_name}
        allowed_refs = required_refs
        ref_name = head_name
    elif ref_type == "lightweight_tag":
        required_refs = {tag_name}
        allowed_refs = {tag_name, head_name}
        ref_name = tag_name
    else:
        required_refs = {tag_name, peeled_name}
        allowed_refs = {tag_name, peeled_name, head_name}
        ref_name = tag_name
    if not required_refs.issubset(refs) or not set(refs).issubset(allowed_refs):
        raise OnlineEvidenceError(
            f"live mutable-ref evidence is missing or ambiguous for {original_ref}"
        )
    if refs[ref_name] != entry["git_ls_remote"]["ref_object"]:
        raise OnlineEvidenceError(f"live ref object contradicts {original_ref}")
    if ref_type == "annotated_tag":
        resolved_ref_commit = refs[peeled_name]
        tag_data = _require_object(tag_payload, "annotated-tag evidence")
        target = _require_object(tag_data.get("object"), "annotated-tag target")
        chain = entry["resolution_chain"]
        expected_target = chain[-1]
        if (
            tag_data.get("sha") != refs[tag_name]
            or tag_data.get("tag") != entry["requested_ref"]
            or target.get("type") != expected_target["target_type"]
            or target.get("sha") != expected_target["target_sha"]
            or target.get("type") != "commit"
            or target.get("sha") != commit_sha
        ):
            raise OnlineEvidenceError(
                f"live annotated-tag chain contradicts {original_ref}"
            )
    else:
        resolved_ref_commit = refs[ref_name]
    if resolved_ref_commit != commit_sha:
        raise OnlineEvidenceError(f"live mutable ref contradicts {original_ref}")


def run_command(command: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            text=True,
            timeout=60,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise OnlineEvidenceError(
            f"command could not complete: {' '.join(command)}: {error}"
        ) from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise OnlineEvidenceError(f"command failed: {' '.join(command)}: {detail}")
    if not completed.stdout.strip():
        raise OnlineEvidenceError(f"command returned no evidence: {' '.join(command)}")
    return completed.stdout


def _run_json(command: Sequence[str], runner: CommandRunner) -> object:
    raw = runner(command)
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise OnlineEvidenceError(
            f"command returned malformed JSON: {' '.join(command)}"
        ) from error


def verify_lock(lock_path: Path, runner: CommandRunner = run_command) -> int:
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OnlineEvidenceError(f"could not load action lock: {lock_path}") from error
    lock_data = _require_object(lock, "action lock")
    actions = lock_data.get("actions")
    if not isinstance(actions, list) or not actions:
        raise OnlineEvidenceError("action lock has no action entries")

    for entry in actions:
        try:
            supply_chain.validate_action_lock_entry(entry)
        except supply_chain.ContractError as error:
            raise OnlineEvidenceError(str(error)) from error
        assert isinstance(entry, dict)
        repository = entry["repository"]
        commit_sha = entry["resolved_commit"]
        action_file = entry["action_file"]
        requested_ref = entry["requested_ref"]
        repository_payload = _run_json(
            ["gh", "api", f"repos/{repository}"], runner
        )
        commit_payload = _run_json(
            ["gh", "api", f"repos/{repository}/commits/{commit_sha}"], runner
        )
        contents_payload = _run_json(
            [
                "gh", "api",
                f"repos/{repository}/contents/{action_file}?ref={commit_sha}",
            ],
            runner,
        )
        head_name, tag_name, peeled_name = ref_query_names(requested_ref)
        ls_remote_output = runner(
            [
                "git", "ls-remote", f"https://github.com/{repository}.git",
                head_name, tag_name, peeled_name,
            ]
        )
        tag_payload = None
        if entry["ref_type"] == "annotated_tag":
            tag_object = entry["git_ls_remote"]["ref_object"]
            tag_payload = _run_json(
                ["gh", "api", f"repos/{repository}/git/tags/{tag_object}"],
                runner,
            )
        validate_live_action_evidence(
            entry, repository_payload, commit_payload, contents_payload,
            ls_remote_output, tag_payload,
        )
    return len(actions)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock", type=Path,
        default=SCRIPT_DIRECTORY / supply_chain.LOCK_NAME,
        help="path to the reviewed action lock",
    )
    arguments = parser.parse_args()
    try:
        count = verify_lock(arguments.lock)
    except OnlineEvidenceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Verified {count} action lock entries against live GitHub evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
