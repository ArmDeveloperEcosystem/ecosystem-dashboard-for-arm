#!/usr/bin/env python3
"""Stage one immutable smoke repair, then publish only live-verified native success.

The caller supplies trusted policy and native-verification functions. Neither this
module nor its publisher job executes candidate code. ``validate_apply(context,
proposal)`` returns the policy's admitted-result mapping. ``verify_native(stage, receipt)``
must perform live API verification and return the receipt unchanged, or raise.
The CLI loads these functions only from sibling, reviewed implementation files.

CLI: admit --context FILE --proposal FILE --output FILE --repository-root DIR
     stage (same flags) --candidate FILE --native-contract FILE
     open-pr (same flags) --stage FILE --native-receipt FILE --native-contract FILE
All receipt outputs must be new files outside the checkout. --policy-version
defaults to 1. A failed write may leave an immutable branch or draft behind;
staging never silently reuses it, while publication can recover an exact draft.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode


DIRECTORY = Path(__file__).resolve().parent


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load trusted implementation: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


publisher = _module(
    "smoke_repair_generated_publisher",
    DIRECTORY.parent / "actions/publish-generated-data-pr/generated_data_pr.py",
)
supply = _module("smoke_repair_supply_chain", DIRECTORY / "package_workflow_supply_chain.py")
from orchestration_contract import decode_json, validate_repository, validate_sha  # noqa: E402

PublishError = publisher.PublishError
Policy = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]]
NativeVerifier = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]]
LOCK_PATH = ".github/scripts/package_workflow_action_lock.json"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
CONTEXT_KEYS = {
    "repository", "base_sha", "orchestration_id", "orchestrator_run_id",
    "orchestrator_run_attempt", "package_slug", "workflow_path", "called_job",
    "source_text", "failed_steps", "log_excerpt",
    "batch", "initial_run_id", "confirmation_run_id", "confirmation_job_id",
}
STAGE_KEYS = {
    "schema_version", "repository", "repair_id", "base_sha", "branch",
    "candidate_sha", "tree_sha", "workflow_path", "package_slug",
    "proposal_digest", "source_digest",
}
AUDIT_KEYS = (STAGE_KEYS - {"candidate_sha"}) | {
    "called_job", "base_source_digest", "context_digest", "native_contract_digest", "policy_version", "publisher",
}


def _json(value: object) -> str:
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise PublishError("repair document exceeds byte limit")
        return text
    except (TypeError, ValueError, RecursionError) as error:
        raise PublishError("repair document is not bounded JSON") from error


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PublishError(f"{label} must be an object")
    return copy.deepcopy(value)


def _positive(value: object, label: str) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise PublishError(f"{label} must be a positive integer")
    return value


def _match(value: object, pattern: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise PublishError(f"invalid {label}")
    return value


def _context(value: Mapping[str, Any]) -> dict[str, Any]:
    context = _object(value, "context")
    if set(context) != CONTEXT_KEYS:
        raise PublishError("context fields do not match the frozen contract")
    _json(context)
    validate_repository(context["repository"])
    validate_sha(context["base_sha"])
    run_id = _positive(context["orchestrator_run_id"], "orchestrator run ID")
    attempt = _positive(context["orchestrator_run_attempt"], "orchestrator attempt")
    if context["orchestration_id"] != f"orchestration-{run_id}-{attempt}":
        raise PublishError("orchestration identity does not match its run and attempt")
    supply.exact_run._slug(context["package_slug"], "package slug")
    workflow = _match(context["workflow_path"], r"\.github/workflows/test-[A-Za-z0-9][A-Za-z0-9_-]{0,99}\.yml", "package workflow path")
    if Path(workflow).name.startswith("test-all-packages"):
        raise PublishError("batch and controller workflows are not package repairs")
    if _positive(context["batch"], "batch") > supply.EXPECTED_BATCHES:
        raise PublishError("batch is outside the registered catalog")
    for key in ("initial_run_id", "confirmation_run_id", "confirmation_job_id"):
        _positive(context[key], key)
    if context["initial_run_id"] == context["confirmation_run_id"]:
        raise PublishError("confirmation must be a distinct run")
    _match(context["called_job"], r"[A-Za-z_][A-Za-z0-9_-]{0,99}", "called job")
    if not isinstance(context["source_text"], str) or not context["source_text"]:
        raise PublishError("context has no original source")
    if not isinstance(context["failed_steps"], list) or not context["failed_steps"]:
        raise PublishError("context has no failed-step evidence")
    if not isinstance(context["log_excerpt"], str):
        raise PublishError("context log excerpt must be text")
    return context


def _proposal(value: Mapping[str, Any], workflow: str) -> dict[str, Any]:
    proposal = _object(value, "proposal")
    if set(proposal) != {"diagnosis", "edits", "unresolved_reason"}:
        raise PublishError("proposal fields do not match the frozen contract")
    _json(proposal)
    if not isinstance(proposal["diagnosis"], str) or not proposal["diagnosis"].strip():
        raise PublishError("proposal requires a diagnosis")
    if proposal["unresolved_reason"] not in (None, ""):
        raise PublishError("unresolved proposals cannot be published")
    edits = proposal["edits"]
    if not isinstance(edits, list) or not 1 <= len(edits) <= 32:
        raise PublishError("proposal must contain bounded edits")
    for edit in edits:
        if (
            not isinstance(edit, dict) or set(edit) != {"path", "old", "new"}
            or edit["path"] != workflow
            or not isinstance(edit["old"], str) or not edit["old"]
            or not isinstance(edit["new"], str)
        ):
            raise PublishError("model edits must target only the selected package workflow")
    return proposal


@dataclass(frozen=True)
class RepairConfig:
    repository: str
    expected_base_sha: str
    repair_id: str
    expected_pr_author_login: str
    base_branch: str = "main"
    credential_source: str = "github-app"

    @property
    def owner(self):
        return self.repository.split("/", 1)[0]

    @property
    def head_branch(self):
        return f"automation/smoke-repair/{self.repair_id}"

    @property
    def repository_url(self):
        return f"https://github.com/{self.repository}"

    @property
    def title(self):
        return f"Repair package smoke: {self.repair_id}"

    @property
    def ownership_marker(self):
        return f"<!-- smoke-repair:{self.repair_id}:v1 -->"


def _runtime(context: dict[str, Any]) -> tuple[RepairConfig, dict[str, Any]]:
    environment = os.environ
    if not environment.get("GH_TOKEN"):
        raise PublishError("dedicated job-scoped GH_TOKEN is required")
    if environment.get("GH_HOST", "github.com") != "github.com":
        raise PublishError("publisher only supports github.com")
    login = environment.get("SMOKE_REPAIR_APP_BOT_LOGIN", "")
    generated_login = environment.get("DASHBOARD_DELIVERY_APP_BOT_LOGIN", "")
    publisher._validate_pr_credentials(login, "github-app")
    publisher._validate_pr_credentials(generated_login, "github-app")
    slug = _match(environment.get("SMOKE_REPAIR_APP_SLUG", ""), r"[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?", "minted App slug")
    if login.casefold() != f"{slug}[bot]".casefold() or login.casefold() == generated_login.casefold():
        raise PublishError("repair App identity is missing, mismatched, or the generated-data App")
    repository, base = context["repository"], context["base_sha"]
    if (
        environment.get("GITHUB_REPOSITORY") != repository
        or environment.get("GITHUB_REF") != "refs/heads/main"
        or environment.get("GITHUB_SHA") != base
        or environment.get("GITHUB_WORKFLOW_SHA") != base
        or environment.get("GITHUB_SERVER_URL", "https://github.com") != "https://github.com"
    ):
        raise PublishError("publisher runtime is not bound to this repository and reviewed main")
    workflow_ref = environment.get("GITHUB_WORKFLOW_REF", "")
    prefix, suffix = f"{repository}/", "@refs/heads/main"
    if not workflow_ref.startswith(prefix) or not workflow_ref.endswith(suffix):
        raise PublishError("publisher workflow ref is not trusted main")
    workflow_path = workflow_ref[len(prefix):-len(suffix)]
    _match(workflow_path, r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", "publisher workflow path")
    run_id = _positive(int(_match(environment.get("GITHUB_RUN_ID", ""), r"[1-9][0-9]{0,18}", "publisher run ID")), "publisher run ID")
    attempt = _positive(int(_match(environment.get("GITHUB_RUN_ATTEMPT", ""), r"[1-9][0-9]{0,18}", "publisher attempt")), "publisher attempt")
    repair_id = f"{context['orchestrator_run_id']}-{context['orchestrator_run_attempt']}-{context['package_slug']}"
    return RepairConfig(repository, base, repair_id, login), {
        "run_id": run_id, "run_attempt": attempt, "workflow_ref": workflow_ref,
        "workflow_sha": base, "app_bot_login": login,
    }


def _runtime_guard(github, config: RepairConfig, runtime: dict[str, Any]) -> None:
    run = github._api("GET", f"repos/{config.repository}/actions/runs/{runtime['run_id']}/attempts/{runtime['run_attempt']}")
    path = runtime["workflow_ref"].split("/", 2)[2].split("@", 1)[0]
    expected = {
        "id": runtime["run_id"], "run_attempt": runtime["run_attempt"],
        "head_sha": config.expected_base_sha, "head_branch": "main", "path": path,
    }
    if not isinstance(run, dict) or any(run.get(key) != value for key, value in expected.items()):
        raise PublishError("live publisher run does not match its runtime metadata")
    if type(run["id"]) is not int or type(run["run_attempt"]) is not int:
        raise PublishError("live publisher run has malformed identity")
    if any(not isinstance(run.get(key), dict) or run[key].get("full_name") != config.repository for key in ("repository", "head_repository")):
        raise PublishError("live publisher run belongs to another repository")


def _clean_base(root: Path, git, config: RepairConfig) -> None:
    if Path(git.text("rev-parse", "--show-toplevel")).resolve() != root:
        raise PublishError("publisher must use a repository root")
    if git.text("config", "--get", "remote.origin.url").removesuffix(".git") != config.repository_url:
        raise PublishError("origin must be the exact credential-free HTTPS repository URL")
    if git.text("rev-parse", "--verify", "HEAD^{commit}") != config.expected_base_sha:
        raise PublishError("publisher checkout must remain on the reviewed base")
    if git.run("diff", "--cached", "--quiet", check=False).returncode:
        raise PublishError("publisher requires an empty index")
    if any(publisher._worktree_candidate_paths(git)):
        raise PublishError("publisher requires a clean worktree")


def _guard(root, git, github, config, runtime):
    _clean_base(root, git, config)
    _runtime_guard(github, config, runtime)
    publisher._assert_remote_base_unchanged(git, config)


def _entry(git, commit: str, path: str) -> tuple[str, str]:
    output = git.run("ls-tree", "-z", commit, "--", path).stdout
    match = re.fullmatch(r"(100644|100755) blob ([0-9a-f]{40})\t" + re.escape(path) + "\x00", output)
    if not match:
        raise PublishError(f"expected one tracked regular blob: {path}")
    return match.group(1), match.group(2)


def _blob_id(text: str) -> str:
    raw = text.encode("utf-8")
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def _read_base(root, git, base, path):
    publisher._verify_required_tracked_paths(git, root, (path,))
    data = (root / path).read_bytes()
    if len(data) > MAX_DOCUMENT_BYTES:
        raise PublishError("base file exceeds byte limit")
    text = data.decode("utf-8")
    if _entry(git, base, path)[1] != _blob_id(text):
        raise PublishError("worktree bytes differ from the exact base blob")
    return text


def _action_locations(value, prefix=()):
    result = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"uses", "container", "services"}:
                result.append((prefix + (key,), child))
            result.extend(_action_locations(child, prefix + (key,)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(_action_locations(child, prefix + (index,)))
    return result


def reseal_workflow_lock(repository_root: Path, *, base_sha: str, workflow_path: str,
                         source: str, repair_id: str) -> str:
    """Mechanically reseal workflow bytes; never update action or topology evidence."""
    root = Path(repository_root)
    git = publisher.Git(root)
    original = _read_base(root, git, base_sha, workflow_path)
    old = supply.exact_run._yaml_mapping(original.encode(), "base workflow")
    new = supply.exact_run._yaml_mapping(source.encode(), "candidate workflow")
    if _action_locations(old) != _action_locations(new):
        raise PublishError("repair changes action references, pins, or container metadata")
    old_jobs, new_jobs = old.get("jobs", {}), new.get("jobs", {})
    if (
        old.get("name") != new.get("name") or set(old_jobs) != set(new_jobs)
        or len(new_jobs) != 1
        or any(old_jobs[key].get("runs-on") != new_jobs[key].get("runs-on") for key in old_jobs)
        or supply.exact_run._collect_reachable_action_references(old, "base", root=root)
        != supply.exact_run._collect_reachable_action_references(new, "candidate", root=root)
    ):
        raise PublishError("repair changes the reviewed execution topology")
    paths = supply.registered_workflows(root) + supply.batch_paths(root)
    snapshot = supply.source_snapshot(root, paths, base_sha)
    if snapshot.get(workflow_path) != original.encode():
        raise PublishError("target workflow is not registered in the base snapshot")
    raw_lock = _read_base(root, git, base_sha, LOCK_PATH)
    lock = decode_json(raw_lock)
    if not isinstance(lock, dict) or lock != supply.load_lock(root):
        raise PublishError("action lock is malformed")
    before = supply.workflow_snapshot_sha256(snapshot)
    if before != lock["hardened_workflow_sha256"]:
        raise PublishError("base workflow digest does not match the action lock")
    snapshot[workflow_path] = source.encode()
    after = supply.workflow_snapshot_sha256(snapshot)
    if before == after:
        raise PublishError("repair must change the package workflow")
    _match(repair_id, r"[1-9][0-9]*-[1-9][0-9]*-[A-Za-z0-9][A-Za-z0-9_-]{0,99}", "repair ID")
    lock["hardened_workflow_sha256"] = after
    lock["hardened_workflow_transition"] = {
        "from_sha256": before, "to_sha256": after,
        "reason": f"Reseal bounded smoke repair {repair_id}; action references, pins, and topology unchanged.",
    }
    supply.validate_hardened_workflow_transition(lock)
    return json.dumps(lock, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def _all_prs(github, config):
    result = []
    for page in range(1, 11):
        query = urlencode({"state": "all", "head": f"{config.owner}:{config.head_branch}", "per_page": 100, "page": page})
        rows = github._api("GET", f"repos/{config.repository}/pulls?{query}")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise PublishError("malformed repair PR history")
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise PublishError("repair PR history exceeds limit")


def _prepare(context, proposal, root, policy, policy_version, github):
    context = _context(context)
    proposal = _proposal(proposal, context["workflow_path"])
    _match(policy_version, r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", "policy version")
    root = Path(root).resolve(strict=True)
    git = publisher.Git(root)
    config, runtime = _runtime(context)
    _clean_base(root, git, config)
    _runtime_guard(github, config, runtime)
    github.setup_git_auth()
    _guard(root, git, github, config, runtime)
    artifact = build_candidate(context, proposal, repository_root=root,
                               validate_apply=policy, policy_version=policy_version)
    _guard(root, git, github, config, runtime)
    return context, proposal, root, git, config, runtime, artifact["candidate_source"], artifact["candidate_lock"], artifact["policy_result"]


def build_candidate(context: Mapping[str, Any], proposal: Mapping[str, Any], *,
                    repository_root: Path, validate_apply: Policy,
                    policy_version: str = "1") -> dict[str, Any]:
    """Token-free, remote-free policy reapplication and mechanical reseal.

    The returned JSON artifact is data for the caller's actionlint/bash -n
    preflight. This function parses YAML but never executes proposed commands.
    """
    context = _context(context)
    proposal = _proposal(proposal, context["workflow_path"])
    _match(policy_version, r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", "policy version")
    root = Path(repository_root).resolve(strict=True)
    git = publisher.Git(root)
    repair_id = f"{context['orchestrator_run_id']}-{context['orchestrator_run_attempt']}-{context['package_slug']}"
    config = RepairConfig(context["repository"], context["base_sha"], repair_id, "")
    _clean_base(root, git, config)
    original = _read_base(root, git, config.expected_base_sha, context["workflow_path"])
    if original != context["source_text"]:
        raise PublishError("context source is not the reviewed workflow")
    admitted = _object(validate_apply(copy.deepcopy(context), copy.deepcopy(proposal)), "policy result")
    source = admitted.get("candidate_source")
    if not isinstance(source, str) or not source or source == original or len(source.encode()) > MAX_DOCUMENT_BYTES:
        raise PublishError("policy did not return a bounded changed source")
    if (
        admitted.get("base_source_sha256") != _digest(original)
        or admitted.get("candidate_source_sha256") != _digest(source)
        or not isinstance(admitted.get("contract"), dict)
        or admitted.get("review_required") is not True
        or admitted.get("semantic_equivalence_proven") is not False
    ):
        raise PublishError("policy result has inconsistent source digests or review requirements")
    lock = reseal_workflow_lock(root, base_sha=config.expected_base_sha,
                               workflow_path=context["workflow_path"], source=source, repair_id=repair_id)
    _clean_base(root, git, config)
    artifact = {
        "schema_version": 1, "repository": config.repository, "base_sha": config.expected_base_sha,
        "repair_id": repair_id, "workflow_path": context["workflow_path"],
        "context_digest": _digest(_json(context)), "proposal_digest": _digest(_json(proposal)),
        "policy_version": policy_version, "candidate_source": source, "candidate_lock": lock,
        "policy_result": admitted,
    }
    _json(artifact)
    return artifact


def _metadata(context, proposal, config, runtime, source, policy_version, native_contract_digest):
    return {
        "schema_version": 1, "repository": config.repository, "repair_id": config.repair_id,
        "base_sha": config.expected_base_sha, "branch": config.head_branch,
        "workflow_path": context["workflow_path"], "package_slug": context["package_slug"],
        "called_job": context["called_job"], "proposal_digest": _digest(_json(proposal)),
        "source_digest": _digest(source), "base_source_digest": _digest(context["source_text"]),
        "context_digest": _digest(_json(context)), "policy_version": policy_version,
        "native_contract_digest": native_contract_digest, "publisher": runtime,
    }


def _commit_message(metadata):
    return f"Stage smoke repair {metadata['repair_id']}\n\nSmoke-Repair-Receipt: {_json(metadata)}\n"


def _candidate_tree(git, config, payloads):
    try:
        for path, source in payloads.items():
            mode, _ = _entry(git, config.expected_base_sha, path)
            blob = git.run("hash-object", "-w", "--stdin", input_text=source).stdout.strip()
            if blob != _blob_id(source):
                raise PublishError("Git did not store the exact candidate bytes")
            git.run("update-index", "--cacheinfo", f"{mode},{blob},{path}")
        if set(publisher._staged_paths(git)) != set(payloads):
            raise PublishError("candidate index does not contain exactly the allowed diff")
        publisher._verify_index_modes(git, tuple(payloads))
        tree = git.text("write-tree")
        validate_sha(tree)
        return tree
    finally:
        git.run("read-tree", config.expected_base_sha)


def stage(context: Mapping[str, Any], proposal: Mapping[str, Any], proposed_source: str, *,
          repository_root: Path, native_contract: Mapping[str, Any], validate_apply: Policy,
          policy_version: str, github=None) -> dict[str, Any]:
    """Create a new incident branch; reject all pre-existing branches or PR history."""
    github = github or publisher.GhClient()
    context, proposal, root, git, config, runtime, source, lock, policy_result = _prepare(
        context, proposal, repository_root, validate_apply, policy_version, github)
    if source != proposed_source:
        raise PublishError("admitted source does not match reapplied policy")
    contract = _object(native_contract, "native contract")
    expected_contract = {
        "called_job": context["called_job"], "workflow_path": context["workflow_path"],
        "source_digest": _digest(source),
        "job_name": policy_result["contract"].get("expected_job_name"),
        "mandatory_steps": policy_result["contract"].get("mandatory_step_names"),
        "gate_step": policy_result["contract"].get("final_gate_step_name"),
    }
    if any(value is None or contract.get(key) != value for key, value in expected_contract.items()):
        raise PublishError("native and policy contracts disagree on the admitted package")
    if publisher._remote_head_sha(git, config.head_branch) is not None or _all_prs(github, config):
        raise PublishError("incident branch or PR history already exists; refusing replay")
    payloads = {context["workflow_path"]: source, LOCK_PATH: lock}
    tree = _candidate_tree(git, config, payloads)
    metadata = _metadata(context, proposal, config, runtime, source, policy_version, _digest(_json(contract)))
    metadata["tree_sha"] = tree
    tree_entries = []
    # Only trusted Git database writes occur here; no candidate checkout or hooks.
    for path, text in payloads.items():
        _guard(root, git, github, config, runtime)
        blob = github._api("POST", f"repos/{config.repository}/git/blobs", {
            "encoding": "base64", "content": base64.b64encode(text.encode()).decode("ascii"),
        })
        if not isinstance(blob, dict) or blob.get("sha") != _blob_id(text):
            raise PublishError("GitHub blob does not match candidate bytes")
        tree_entries.append({"path": path, "mode": _entry(git, config.expected_base_sha, path)[0], "type": "blob", "sha": blob["sha"]})
    _guard(root, git, github, config, runtime)
    remote_tree = github._api("POST", f"repos/{config.repository}/git/trees", {
        "base_tree": git.text("rev-parse", f"{config.expected_base_sha}^{{tree}}"), "tree": tree_entries,
    })
    if not isinstance(remote_tree, dict) or remote_tree.get("sha") != tree:
        raise PublishError("GitHub candidate tree differs from the local allowlisted tree")
    _guard(root, git, github, config, runtime)
    commit = github._api("POST", f"repos/{config.repository}/git/commits", {
        "message": _commit_message(metadata), "tree": tree, "parents": [config.expected_base_sha],
    })
    if not isinstance(commit, dict):
        raise PublishError("GitHub returned an invalid candidate commit")
    candidate = validate_sha(commit.get("sha"))
    if (
        commit.get("tree", {}).get("sha") != tree
        or [parent.get("sha") for parent in commit.get("parents", [])] != [config.expected_base_sha]
        or commit.get("message", "").rstrip("\n") != _commit_message(metadata).rstrip("\n")
    ):
        raise PublishError("GitHub candidate commit does not bind the staged receipt")
    _guard(root, git, github, config, runtime)
    if publisher._remote_head_sha(git, config.head_branch) is not None or _all_prs(github, config):
        raise PublishError("incident branch or PR appeared during staging")
    github._api("POST", f"repos/{config.repository}/git/refs", {
        "ref": f"refs/heads/{config.head_branch}", "sha": candidate,
    })
    receipt = {key: value for key, value in {**metadata, "candidate_sha": candidate}.items() if key in STAGE_KEYS}
    _guard(root, git, github, config, runtime)
    if _verify_branch(git, config, receipt, payloads) != metadata:
        raise PublishError("staged commit audit differs from its trusted producer")
    return receipt


def _verify_branch(git, config, receipt, payloads):
    candidate = receipt["candidate_sha"]
    if publisher._remote_head_sha(git, config.head_branch) != candidate:
        raise PublishError("incident branch no longer matches its stage receipt")
    git.run("fetch", "--no-tags", "origin", f"refs/heads/{config.head_branch}")
    if git.text("rev-parse", "--verify", "FETCH_HEAD^{commit}") != candidate:
        raise PublishError("incident branch changed during fetch")
    if git.text("show", "-s", "--format=%P", candidate).split() != [config.expected_base_sha]:
        raise PublishError("incident branch is not one commit on the reviewed base")
    if git.text("rev-parse", f"{candidate}^{{tree}}") != receipt["tree_sha"]:
        raise PublishError("candidate tree does not match stage receipt")
    message = git.run("show", "-s", "--format=%B", candidate).stdout.rstrip("\n")
    prefix = f"Stage smoke repair {config.repair_id}\n\nSmoke-Repair-Receipt: "
    if not message.startswith(prefix):
        raise PublishError("candidate commit has no exact repair ownership receipt")
    metadata = decode_json(message[len(prefix):])
    if (
        not isinstance(metadata, dict) or set(metadata) != AUDIT_KEYS
        or message != _commit_message(metadata).rstrip("\n")
        or any(metadata.get(key) != value for key, value in receipt.items() if key != "candidate_sha")
    ):
        raise PublishError("candidate audit does not bind the exact stage receipt")
    changes = git.run("diff", "--name-only", "--no-renames", "-z", config.expected_base_sha, candidate, "--").stdout
    if set(publisher._nul_paths(changes, description="candidate diff")) != set(payloads):
        raise PublishError("candidate diff extends outside the admitted workflow and mechanical lock")
    for path, source in payloads.items():
        mode, blob = _entry(git, candidate, path)
        if mode != _entry(git, config.expected_base_sha, path)[0] or blob != _blob_id(source):
            raise PublishError("candidate source, file mode, or resealed lock changed")
    if publisher._remote_head_sha(git, config.head_branch) != candidate:
        raise PublishError("incident branch changed during verification")
    return metadata


def _native(receipt, stage_receipt, config, contract_digest):
    result = _object(receipt, "native receipt")
    _json(result)
    if (
        set(result) != {"schema_version", "stage", "contract_digest", "status", "run", "job", "steps"}
        or type(result.get("schema_version")) is not int or result["schema_version"] != 1
        or result.get("stage") != stage_receipt or result.get("status") != "passed"
        or result.get("contract_digest") != contract_digest
    ):
        raise PublishError("native validation is not passed or is bound to another candidate")
    run = _object(result["run"], "native run")
    job = _object(result["job"], "native job")
    run_id = _positive(run.get("id"), "native run ID")
    job_id = _positive(job.get("id"), "native job ID")
    expected = {"head_sha": stage_receipt["candidate_sha"], "head_branch": stage_receipt["branch"],
                "path": stage_receipt["workflow_path"], "event": "workflow_dispatch",
                "status": "completed", "conclusion": "success", "run_attempt": 1,
                "repository": config.repository, "head_repository": config.repository}
    if any(run.get(key) != value for key, value in expected.items()) or type(run.get("run_attempt")) is not int:
        raise PublishError("native run is not exact successful attempt 1")
    if (
        run.get("html_url") != f"{config.repository_url}/actions/runs/{run_id}"
        or job.get("html_url") != f"{config.repository_url}/actions/runs/{run_id}/job/{job_id}"
    ):
        raise PublishError("native evidence URLs do not match run/job identities")
    if job.get("conclusion") != "success" or not isinstance(result["steps"], list) or not result["steps"]:
        raise PublishError("native receipt has no successful job/step evidence")
    return result


def _pr_body(config, stage_receipt, native, policy_version, context):
    return (
        f"{config.ownership_marker}\n# Smoke repair review\n\n"
        f"- Package: `{stage_receipt['package_slug']}`\n"
        f"- Base: `{stage_receipt['base_sha']}`\n"
        f"- Candidate: `{stage_receipt['candidate_sha']}`\n"
        f"- Original failure: {config.repository_url}/actions/runs/{context['initial_run_id']}\n"
        f"- Confirmation failure: {config.repository_url}/actions/runs/{context['confirmation_run_id']}/job/{context['confirmation_job_id']}\n"
        f"- Native package workflow: {native['run']['html_url']} (attempt 1)\n"
        f"- Verified package job: {native['job']['html_url']}\n"
        f"- Policy: `{policy_version}`\n"
        f"- Stage receipt SHA-256: `{_digest(_json(stage_receipt))}`\n"
        f"- Native receipt SHA-256: `{_digest(_json(native))}`\n\n"
        "Native package workflow validation passed. This is not full-fleet validation "
        "or a deployment. The action lock change is a trusted mechanical reseal. "
        "Independent human review and required checks remain mandatory. "
        "This automation does not approve, merge, or deploy.\n"
    )


def open_pr(context: Mapping[str, Any], proposal: Mapping[str, Any], stage_receipt: Mapping[str, Any],
            native_receipt: Mapping[str, Any], *, repository_root: Path, validate_apply: Policy,
            policy_version: str, verify_native: NativeVerifier, github=None) -> dict[str, Any]:
    """Open/recover one exact draft after the callback revalidates native evidence live.

    Native receipt uses smoke_repair_native's schema: schema_version, stage,
    contract_digest, status, run, job, steps. No supplied success verdict replaces
    verify_native. The callback may close over the trusted native contract.
"""
    github = github or publisher.GhClient()
    context, proposal, root, git, config, runtime, source, lock, _ = _prepare(
        context, proposal, repository_root, validate_apply, policy_version, github)
    staged = _object(stage_receipt, "stage receipt")
    if set(staged) != STAGE_KEYS or type(staged.get("schema_version")) is not int or staged["schema_version"] != 1:
        raise PublishError("unsupported stage receipt schema")
    _json(staged)
    for field in ("candidate_sha", "tree_sha"):
        validate_sha(staged[field])
    payloads = {context["workflow_path"]: source, LOCK_PATH: lock}
    if staged["candidate_sha"] == staged["base_sha"]:
        raise PublishError("candidate must differ from base")
    for key, value in {
        "repository": config.repository, "repair_id": config.repair_id, "base_sha": config.expected_base_sha,
        "branch": config.head_branch, "workflow_path": context["workflow_path"],
        "package_slug": context["package_slug"], "source_digest": _digest(source),
        "proposal_digest": _digest(_json(proposal)),
    }.items():
        if staged.get(key) != value:
            raise PublishError("stage receipt does not match context, proposal, source, or policy")
    audit = _verify_branch(git, config, staged, payloads)
    _match(audit["native_contract_digest"], r"[0-9a-f]{64}", "native contract digest")
    producer = _object(audit["publisher"], "stage publisher identity")
    if set(producer) != set(runtime) or producer["app_bot_login"] != config.expected_pr_author_login:
        raise PublishError("stage receipt belongs to another App or has malformed runtime metadata")
    # The producer may be a previous job/run, but never another workflow or base.
    if producer["workflow_ref"] != runtime["workflow_ref"] or producer["workflow_sha"] != runtime["workflow_sha"]:
        raise PublishError("stage was produced by another trusted workflow or base")
    _positive(producer["run_id"], "stage publisher run ID")
    _positive(producer["run_attempt"], "stage publisher attempt")
    _runtime_guard(github, config, producer)
    expected = _metadata(context, proposal, config, producer, source, policy_version, audit["native_contract_digest"])
    expected["tree_sha"] = staged["tree_sha"]
    if audit != expected:
        raise PublishError("stage audit does not match context, source, policy, or producer")
    native = _native(native_receipt, staged, config, audit["native_contract_digest"])
    verified = verify_native(copy.deepcopy(staged), copy.deepcopy(native))
    if _json(verified) != _json(native):
        raise PublishError("native verifier must return the unchanged live-verified receipt")
    _guard(root, git, github, config, runtime)
    _verify_branch(git, config, staged, payloads)
    body = _pr_body(config, staged, native, policy_version, context)
    history = _all_prs(github, config)
    existing = publisher._one_owned_open_pull_request(config, history)
    if existing is not None:
        if existing["head"]["sha"] != staged["candidate_sha"] or existing.get("body") != body or existing.get("title") != config.title:
            raise PublishError("existing repair draft differs from the exact verified audit")
        result = existing
        status = "unchanged"
    else:
        _guard(root, git, github, config, runtime)
        _verify_branch(git, config, staged, payloads)
        if _all_prs(github, config):
            raise PublishError("repair PR appeared during publication")
        if _json(verify_native(copy.deepcopy(staged), copy.deepcopy(native))) != _json(native):
            raise PublishError("native validation changed immediately before publication")
        _guard(root, git, github, config, runtime)
        _verify_branch(git, config, staged, payloads)
        result = github.create_pull_request(config, body=body, head_sha=staged["candidate_sha"])
        publisher._validate_pull_request_ownership(config, result, expected_state="open")
        status = "created"
    verified_pr = publisher._wait_for_exact_pull_request(
        config, github, expected_number=publisher._pull_request_number(result),
        expected_head_sha=staged["candidate_sha"], expected_body=body,
    )
    expected_url = f"{config.repository_url}/pull/{publisher._pull_request_number(verified_pr)}"
    if verified_pr.get("html_url") != expected_url:
        raise PublishError("published PR URL does not match its identity")
    _guard(root, git, github, config, runtime)
    _verify_branch(git, config, staged, payloads)
    if _json(verify_native(copy.deepcopy(staged), copy.deepcopy(native))) != _json(native):
        raise PublishError("native validation changed during publication")
    _guard(root, git, github, config, runtime)
    _verify_branch(git, config, staged, payloads)
    return {"status": status, "pr_url": expected_url, "head_sha": staged["candidate_sha"],
            "repair_id": staged["repair_id"], "native_run_id": native["run"]["id"], "publisher": runtime}


def _load(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise PublishError("input must be a bounded regular file")
    return decode_json(path.read_bytes())


def _write_publication_outputs(result, repository):
    output_path = os.environ.get("GITHUB_OUTPUT")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not output_path and not summary_path:
        return
    validate_repository(repository)
    if result.get("status") not in {"created", "unchanged"}:
        raise PublishError("only successful draft publication can emit workflow outputs")
    url = _match(result.get("pr_url"), rf"https://github\.com/{re.escape(repository)}/pull/[1-9][0-9]*", "published PR URL")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"pull_request_url={url}\n")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(f"\n[Smoke repair draft PR]({url})\n\nHuman review and required PR checks remain pending.\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("admit", "stage", "open-pr"):
        command = subparsers.add_parser(name)
        for flag in ("context", "proposal", "output"):
            command.add_argument(f"--{flag}", required=True, type=Path)
        command.add_argument("--policy-version", default="1")
        command.add_argument("--repository-root", type=Path, default=Path.cwd())
        if name != "admit":
            command.add_argument("--native-contract", required=True, type=Path)
        if name == "stage":
            command.add_argument("--candidate", required=True, type=Path)
        elif name == "open-pr":
            command.add_argument("--stage", required=True, type=Path)
            command.add_argument("--native-receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        output = args.output.parent.resolve(strict=True) / args.output.name
        if output.is_relative_to(args.repository_root.resolve()) or output.exists() or output.is_symlink():
            raise PublishError("receipt output must be new and outside the repository checkout")
        policy = _module("smoke_repair_cli_policy", DIRECTORY / "smoke_repair_policy.py")
        if str(policy.POLICY_VERSION) != args.policy_version:
            raise PublishError("CLI policy version differs from trusted policy implementation")
        kwargs = {"repository_root": args.repository_root,
                  "validate_apply": policy.validate_proposal,
                  "policy_version": args.policy_version}
        context, proposal = _load(args.context), _load(args.proposal)
        if args.command == "admit":
            result = build_candidate(context, proposal, **kwargs)
        elif args.command == "stage":
            admitted = _load(args.candidate)
            if _json(admitted) != _json(build_candidate(context, proposal, **kwargs)):
                raise PublishError("preflight candidate artifact differs from reapplied admission")
            result = stage(context, proposal, admitted["candidate_source"],
                           native_contract=_load(args.native_contract), **kwargs)
        else:
            native = _module("smoke_repair_cli_native", DIRECTORY / "smoke_repair_native.py")
            contract = _load(args.native_contract)
            verification_deadline = time.monotonic() + 180
            result = open_pr(context, proposal, _load(args.stage), _load(args.native_receipt),
                             verify_native=lambda staged, receipt: native.verify_native_receipt(
                                 staged, receipt, contract, deadline=verification_deadline), **kwargs)
        # Receipts are written outside the checkout, never staged as candidate files.
        with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
            stream.write(_json(result) + "\n")
        if args.command == "open-pr":
            _write_publication_outputs(result, context["repository"])
        return 0
    except Exception:
        # Dependency errors can include remote responses, proposal text, or secrets.
        print("smoke repair publication failed closed; no successful repair is claimed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
