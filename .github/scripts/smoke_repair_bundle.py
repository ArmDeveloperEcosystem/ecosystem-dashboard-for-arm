"""Immutable multi-package repair staging and full-fleet-gated draft publication.

``readmit(request, ...)`` is token-free and never executes candidate commands.
``stage(request, admitted, ...)`` returns ``{candidate, attestation}``. Candidate is
the seven-field descriptor shared with the fleet worker; the attestation is
publisher-owned data, not model output. ``verify`` reconstructs both commits and
all changed bytes. ``open_draft`` additionally requires live fleet verification.

Only reviewed controller code may provide the required callbacks. ``verify_current``
must authenticate the request's original failure evidence, current main, cycle,
and active iteration and return the unchanged request. ``verify_fleet`` must
authenticate every required native batch/package and summary at the exact final
candidate, returning the unchanged receipt. A supplied JSON success flag is not
authorization. The CLI imports only reviewed sibling implementations.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_repair_publisher as single
from smoke_repair_session import VerificationSession, session_for
from orchestration_contract import validate_current_ref, validate_repository, validate_sha


PublishError = single.PublishError
publisher = single.publisher
MAX_PACKAGES = 1024
MAX_ITERATIONS = 3
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
REQUEST_KEYS = {"schema_version", "repository", "base_sha", "cycle_id", "iteration", "packages"}
DESCRIPTOR_KEYS = {"schema_version", "repository", "base_sha", "candidate_sha", "branch", "cycle_id", "iteration"}
ATTESTATION_KEYS = {
    "schema_version", "tree_sha", "source_anchor", "request_digest", "plan_digest",
    "policy_version", "package_digests", "publisher",
}
CurrentVerifier = Callable[[dict[str, Any]], Mapping[str, Any]]
FleetVerifier = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]]


def _json(value):
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(result.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise PublishError("bundle document exceeds byte limit")
        return result
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise PublishError("bundle must be bounded JSON") from exc


def _digest(value):
    return single._digest(_json(value))


def _request(value):
    request = single._object(value, "bundle request")
    if (set(request) != REQUEST_KEYS or type(request.get("schema_version")) is not int
            or request["schema_version"] != 1):
        raise PublishError("unsupported bundle request schema")
    _json(request)
    validate_repository(request["repository"])
    validate_sha(request["base_sha"])
    if not 1 <= single._positive(request["iteration"], "iteration") <= MAX_ITERATIONS:
        raise PublishError("bundle iteration exceeds bound")
    single._match(request["cycle_id"], r"[1-9][0-9]{0,18}-[1-9][0-9]{0,18}", "cycle ID")
    packages = request["packages"]
    if not isinstance(packages, list) or not 1 <= len(packages) <= MAX_PACKAGES:
        raise PublishError("bundle requires a bounded nonempty package inventory")
    slugs, paths = set(), set()
    for item in packages:
        if not isinstance(item, dict) or set(item) != {"context", "proposal"}:
            raise PublishError("bundle packages contain context and proposal only")
        context = single._context(item["context"])
        single._proposal(item["proposal"], context["workflow_path"])
        if (context["repository"] != request["repository"]
                or context["base_sha"] != request["base_sha"]
                or context["orchestration_id"] != f"orchestration-{request['cycle_id']}"):
            raise PublishError("bundle packages must share exact base, repository, and cycle")
        slug, path = context["package_slug"], context["workflow_path"]
        if path != f".github/workflows/test-{slug}.yml":
            raise PublishError("bundle package must use its canonical workflow path")
        if slug.casefold() in slugs or path.casefold() in paths:
            raise PublishError("duplicate or colliding bundle package")
        slugs.add(slug.casefold())
        paths.add(path.casefold())
    if [item["context"]["package_slug"] for item in packages] != sorted(
            item["context"]["package_slug"] for item in packages):
        raise PublishError("bundle packages must be canonically sorted")
    return request


@dataclass(frozen=True)
class BundleConfig(single.RepairConfig):
    cycle_id: str = ""
    iteration: int = 1

    @property
    def head_branch(self):
        return f"automation/smoke-repair-cycle/{self.cycle_id}/iteration-{self.iteration}"

    @property
    def title(self):
        return f"Repair smoke cycle {self.cycle_id}, iteration {self.iteration}"

    @property
    def ownership_marker(self):
        return f"<!-- smoke-repair-bundle:{self.cycle_id}:{self.iteration}:v1 -->"


def _config(request, login=""):
    context = request["packages"][0]["context"]
    repair_id = f"{context['orchestrator_run_id']}-{context['orchestrator_run_attempt']}-bundle-{request['iteration']}"
    return BundleConfig(request["repository"], request["base_sha"], repair_id, login,
                        cycle_id=request["cycle_id"], iteration=request["iteration"])


def _identity(request, config):
    return {"schema_version": 1, "repository": request["repository"], "base_sha": request["base_sha"],
            "branch": config.head_branch, "cycle_id": request["cycle_id"], "iteration": request["iteration"]}


def validate_descriptor(value):
    candidate = single._object(value, "bundle candidate")
    if (set(candidate) != DESCRIPTOR_KEYS or type(candidate.get("schema_version")) is not int
            or candidate["schema_version"] != 1):
        raise PublishError("unsupported bundle descriptor")
    validate_repository(candidate["repository"])
    for field in ("base_sha", "candidate_sha"):
        validate_sha(candidate[field])
    if candidate["base_sha"] == candidate["candidate_sha"]:
        raise PublishError("bundle candidate must differ from base")
    single._match(candidate["cycle_id"], r"[1-9][0-9]{0,18}-[1-9][0-9]{0,18}", "cycle ID")
    if not 1 <= single._positive(candidate["iteration"], "iteration") <= MAX_ITERATIONS:
        raise PublishError("bundle iteration exceeds bound")
    expected_branch = f"automation/smoke-repair-cycle/{candidate['cycle_id']}/iteration-{candidate['iteration']}"
    if candidate["branch"] != expected_branch:
        raise PublishError("bundle branch does not bind cycle and iteration")
    return candidate


def readmit(request: Mapping[str, Any], *, repository_root: Path,
            validate_apply: single.Policy, policy_version: str = "1") -> dict[str, Any]:
    """Reapply the original policy independently, then reseal the combined snapshot."""
    request = _request(request)
    root = Path(repository_root).resolve(strict=True)
    config = _config(request)
    git = publisher.Git(root)
    single._clean_base(root, git, config)
    packages = []
    catalog_digest = None
    for item in request["packages"]:
        admitted = single.build_candidate(item["context"], item["proposal"], repository_root=root,
                                          validate_apply=validate_apply, policy_version=policy_version)
        if admitted["catalog_base_digest"] is None:
            raise PublishError("bundle staging requires the reviewed identity catalog")
        if catalog_digest not in (None, admitted["catalog_base_digest"]):
            raise PublishError("bundle packages do not share their reviewed catalog")
        catalog_digest = admitted["catalog_base_digest"]
        packages.append({
            "package_slug": item["context"]["package_slug"], "workflow_path": admitted["workflow_path"],
            "context_digest": admitted["context_digest"], "proposal_digest": admitted["proposal_digest"],
            "base_source_digest": single._digest(item["context"]["source_text"]),
            "source_digest": single._digest(admitted["candidate_source"]),
            "candidate_source": admitted["candidate_source"],
            "policy_result_digest": _digest(admitted["policy_result"]),
        })
    paths = single.supply.registered_workflows(root) + single.supply.batch_paths(root)
    snapshot = single.supply.source_snapshot(root, paths, config.expected_base_sha)
    lock = single.decode_json(single._read_base(root, git, config.expected_base_sha, single.LOCK_PATH))
    before = single.supply.workflow_snapshot_sha256(snapshot)
    if before != lock["hardened_workflow_sha256"]:
        raise PublishError("bundle base snapshot differs from reviewed action lock")
    for package, item in zip(packages, request["packages"]):
        path = package["workflow_path"]
        if snapshot.get(path) != item["context"]["source_text"].encode("utf-8"):
            raise PublishError("bundle source differs from reviewed snapshot")
        snapshot[path] = package["candidate_source"].encode("utf-8")
    after = single.supply.workflow_snapshot_sha256(snapshot)
    if before == after:
        raise PublishError("bundle must change the workflow snapshot")
    lock["hardened_workflow_sha256"] = after
    lock["hardened_workflow_transition"] = {
        "from_sha256": before, "to_sha256": after,
        "reason": f"Reseal bounded smoke repair {config.repair_id}; action references, pins, and topology unchanged.",
    }
    single.supply.validate_hardened_workflow_transition(lock)
    result = {
        **_identity(request, config), "request_digest": _digest(request), "policy_version": policy_version,
        "packages": packages, "catalog_base_digest": catalog_digest,
        "candidate_lock": json.dumps(lock, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
    }
    _json(result)
    single._clean_base(root, git, config)
    return result


def _current(request, verifier):
    if not callable(verifier) or _json(verifier(copy.deepcopy(request))) != _json(request):
        raise PublishError("current cycle verifier must return the unchanged authenticated request")


class _GuardedGitHub:
    """Extend existing Git-object helpers with the bundle's current-iteration guard."""

    def __init__(self, github, guard):
        self.github, self.guard = github, guard

    def _api(self, method, endpoint, payload=None):
        if method != "GET":
            self.guard()
        return self.github._api(method, endpoint, payload) if payload is not None else self.github._api(method, endpoint)


def _prepare(request, root, policy, version, current, github):
    request = _request(request)
    root = Path(root).resolve(strict=True)
    admitted = readmit(request, repository_root=root, validate_apply=policy, policy_version=version)
    identity, runtime = single._runtime(request["packages"][0]["context"])
    if runtime["workflow_ref"] != f"{request['repository']}/.github/workflows/smoke-repair-cycle.yml@refs/heads/main":
        raise PublishError("bundle publisher must execute the trusted-main cycle workflow")
    config, git = _config(request, identity.expected_pr_author_login), publisher.Git(root)
    _current(request, current)
    single._clean_base(root, git, config)
    single._runtime_guard(github, config, runtime)
    github.setup_git_auth()

    def guard():
        _current(request, current)
        single._guard(root, git, github, config, runtime)

    guard()
    return request, root, git, config, runtime, admitted, guard


def _package_digests(admitted):
    return [{key: value for key, value in item.items() if key != "candidate_source"}
            for item in admitted["packages"]]


def _attestation(admitted, runtime, tree, anchor):
    return {"schema_version": 1, "tree_sha": tree, "source_anchor": anchor,
            "request_digest": admitted["request_digest"], "plan_digest": _digest(admitted),
            "policy_version": admitted["policy_version"], "package_digests": _package_digests(admitted),
            "publisher": runtime}


def _message(identity, attestation, *, source=False):
    label = "Source" if source else "Receipt"
    return f"Smoke repair bundle {identity['cycle_id']} iteration {identity['iteration']}\n\nSmoke-Repair-Bundle-{label}: {_json({'candidate': identity, **attestation})}\n"


def _payloads(request, admitted, root, git, config, anchor):
    single._validate_anchor(anchor, base_sha=request["base_sha"])
    if anchor is None:
        raise PublishError("bundle requires a source anchor")
    raw = single._read_base(root, git, request["base_sha"], single.CATALOG_PATH)
    if single._digest(raw) != admitted["catalog_base_digest"]:
        raise PublishError("bundle catalog bytes changed")
    sources = {}
    for item, package in zip(request["packages"], admitted["packages"]):
        context = item["context"]
        try:
            raw = single.bindings.rebind_catalog(
                raw, package_slug=context["package_slug"], workflow_path=context["workflow_path"],
                original_source=context["source_text"], candidate_source=package["candidate_source"],
                source_commit=anchor["sha"], verified_by=config.expected_pr_author_login,
                verified_at=anchor["verified_at"],
            )
        except ValueError as exc:
            raise PublishError("bundle catalog cannot be mechanically rebound") from exc
        sources[context["workflow_path"]] = package["candidate_source"]
    return {**sources, single.LOCK_PATH: admitted["candidate_lock"], single.CATALOG_PATH: raw}


def _verify_branch(request, admitted, root, git, config, staged):
    if not isinstance(staged, dict) or set(staged) != {"candidate", "attestation"}:
        raise PublishError("bundle stage must contain candidate and attestation only")
    descriptor = validate_descriptor(staged["candidate"])
    identity = _identity(request, config)
    if any(descriptor[key] != value for key, value in identity.items()):
        raise PublishError("bundle stage belongs to a different cycle or iteration")
    audit = single._object(staged["attestation"], "bundle attestation")
    if (set(audit) != ATTESTATION_KEYS or type(audit.get("schema_version")) is not int
            or audit["schema_version"] != 1):
        raise PublishError("unsupported bundle attestation")
    _json(audit)
    validate_sha(audit["tree_sha"])
    candidate, anchor = descriptor["candidate_sha"], audit["source_anchor"]
    single._validate_anchor(anchor, base_sha=request["base_sha"], candidate_sha=candidate)
    payloads = _payloads(request, admitted, root, git, config, anchor)
    if audit != _attestation(admitted, audit["publisher"], audit["tree_sha"], anchor):
        raise PublishError("bundle audit differs from independent policy readmission")
    if publisher._remote_head_sha(git, config.head_branch) != candidate:
        raise PublishError("bundle branch no longer matches its immutable candidate")
    git.run("fetch", "--no-tags", "origin", f"refs/heads/{config.head_branch}")
    if git.text("rev-parse", "--verify", "FETCH_HEAD^{commit}") != candidate:
        raise PublishError("bundle branch changed during fetch")
    source_payloads = {path: text for path, text in payloads.items()
                       if path not in {single.LOCK_PATH, single.CATALOG_PATH}}
    source_audit = {**audit, "source_anchor": None, "tree_sha": anchor["tree_sha"]}
    for sha, parent, tree, message, expected_files in (
        (anchor["sha"], request["base_sha"], anchor["tree_sha"],
         _message(identity, source_audit, source=True), source_payloads),
        (candidate, anchor["sha"], audit["tree_sha"], _message(identity, audit), payloads),
    ):
        if (git.text("show", "-s", "--format=%P", sha).split() != [parent]
                or git.text("rev-parse", f"{sha}^{{tree}}") != tree
                or git.run("show", "-s", "--format=%B", sha).stdout.rstrip("\n") != message.rstrip("\n")):
            raise PublishError("bundle commit ancestry, tree, or publisher receipt changed")
        changes = git.run("diff", "--name-only", "--no-renames", "-z", request["base_sha"], sha, "--").stdout
        if set(publisher._nul_paths(changes, description="bundle diff")) != set(expected_files):
            raise PublishError("bundle diff is not the exact admitted path allowlist")
        for path, text in expected_files.items():
            if single._entry(git, sha, path) != (single._entry(git, request["base_sha"], path)[0], single._blob_id(text)):
                raise PublishError("bundle contains changed bytes or file modes")
    if single._utc_timestamp(git.text("show", "-s", "--format=%cI", anchor["sha"])) != anchor["verified_at"]:
        raise PublishError("bundle source anchor timestamp changed")
    if publisher._remote_head_sha(git, config.head_branch) != candidate:
        raise PublishError("bundle branch changed during verification")
    return audit


def _producer(github, config, runtime, audit):
    producer = single._object(audit["publisher"], "bundle producer")
    if set(producer) != set(runtime):
        raise PublishError("bundle producer schema differs from trusted runtime")
    for key in ("workflow_ref", "workflow_sha", "app_bot_login"):
        if producer[key] != runtime[key]:
            raise PublishError("bundle was produced by another workflow, base, or App")
    for key in ("run_id", "run_attempt"):
        single._positive(producer[key], key)
    single._runtime_guard(github, config, producer)


def stage(request: Mapping[str, Any], admitted: Mapping[str, Any], *, repository_root: Path,
          validate_apply: single.Policy, verify_current: CurrentVerifier,
          policy_version: str = "1", github=None) -> dict[str, Any]:
    """Create a fresh source-anchor/binding pair; never update or reuse a branch."""
    github = github or publisher.GhClient()
    request, root, git, config, runtime, plan, guard = _prepare(
        request, repository_root, validate_apply, policy_version, verify_current, github)
    if _json(admitted) != _json(plan):
        raise PublishError("bundle preflight differs from independent readmission")
    if publisher._remote_head_sha(git, config.head_branch) is not None or single._all_prs(github, config):
        raise PublishError("bundle branch or PR history already exists; refusing replay")
    identity = _identity(request, config)
    sources = {item["workflow_path"]: item["candidate_source"] for item in plan["packages"]}
    tree = single._candidate_tree(git, config, sources)
    source_audit = _attestation(plan, runtime, tree, None)
    guarded = _GuardedGitHub(github, guard)
    source = single._publish_commit(root, git, guarded, config, runtime, sources, tree,
                                    _message(identity, source_audit, source=True), config.expected_base_sha)
    anchor = {"sha": source["sha"], "tree_sha": tree,
              "verified_at": single._utc_timestamp(source.get("committer", {}).get("date"))}
    payloads = _payloads(request, plan, root, git, config, anchor)
    final_tree = single._candidate_tree(git, config, payloads)
    audit = _attestation(plan, runtime, final_tree, anchor)
    final = single._publish_commit(root, git, guarded, config, runtime, payloads, final_tree,
                                   _message(identity, audit), anchor["sha"])
    guard()
    if publisher._remote_head_sha(git, config.head_branch) is not None or single._all_prs(github, config):
        raise PublishError("bundle branch or PR appeared during staging")
    result = {"candidate": {**identity, "candidate_sha": final["sha"]}, "attestation": audit}
    guarded._api("POST", f"repos/{config.repository}/git/refs",
                 {"ref": f"refs/heads/{config.head_branch}", "sha": final["sha"]})
    guard()
    if _verify_branch(request, plan, root, git, config, result) != audit:
        raise PublishError("bundle receipt differs from staged branch")
    guard()
    return result


def verify(request: Mapping[str, Any], staged: Mapping[str, Any], *, repository_root: Path,
           validate_apply: single.Policy, verify_current: CurrentVerifier,
           policy_version: str = "1", github=None) -> dict[str, Any]:
    """Reauthenticate the complete immutable candidate; this does not claim tests pass."""
    github = github or publisher.GhClient()
    request, root, git, config, runtime, plan, guard = _prepare(
        request, repository_root, validate_apply, policy_version, verify_current, github)
    staged = single._object(staged, "bundle stage")
    audit = _verify_branch(request, plan, root, git, config, staged)
    _producer(github, config, runtime, audit)
    guard()
    return staged


def _fleet(descriptor, receipt, verifier):
    receipt = single._object(receipt, "fleet receipt")
    _json(receipt)
    if (type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1
            or receipt.get("descriptor") != descriptor or receipt.get("status") != "success"
            or receipt.get("kind") != "smoke-repair-candidate-fleet" or receipt.get("publishing") is not False):
        raise PublishError("fleet receipt does not bind passed validation of this exact candidate")
    if not callable(verifier) or _json(verifier(copy.deepcopy(descriptor), copy.deepcopy(receipt))) != _json(receipt):
        raise PublishError("fleet verifier must return the unchanged live-verified receipt")
    return receipt


def _body(config, staged, fleet):
    candidate, audit = staged["candidate"], staged["attestation"]
    packages = ", ".join(f"`{item['package_slug']}`" for item in audit["package_digests"])
    # No model diagnosis, free-form URLs, or verifier-provided prose is published.
    return (
        f"{config.ownership_marker}\n# Smoke recovery review\n\n"
        f"- Cycle: `{candidate['cycle_id']}`, iteration `{candidate['iteration']}`\n"
        f"- Packages: {packages}\n- Base: `{candidate['base_sha']}`\n"
        f"- Candidate: `{candidate['candidate_sha']}`\n"
        f"- Publisher attestation SHA-256: `{_digest(audit)}`\n"
        f"- Full-fleet receipt SHA-256: `{_digest(fleet)}`\n\n"
        "All required candidate batches, package jobs, and Global Summary were verified by the trusted fleet worker. "
        "This is candidate validation, not proof that main or production has changed. "
        "Lock and catalog changes are mechanical source bindings. Merge with a merge commit, not squash or rebase, "
        "to preserve the catalog source anchor. Human review and required checks remain mandatory. "
        "This automation does not approve, merge, or deploy.\n"
    )


def open_draft(request: Mapping[str, Any], staged: Mapping[str, Any], fleet_receipt: Mapping[str, Any], *,
               repository_root: Path, validate_apply: single.Policy, verify_current: CurrentVerifier,
               verify_fleet: FleetVerifier, policy_version: str = "1", github=None,
               deadline=None) -> dict[str, Any]:
    """Open/recover only an exact draft after fresh full-fleet verification."""
    if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise PublishError("publication deadline must be finite")
    from smoke_repair_fleet import VERIFY_SECONDS
    limit = time.monotonic() + VERIFY_SECONDS
    deadline = limit if deadline is None else min(limit, deadline)
    single._publication_remaining(deadline)
    github = github or publisher.GhClient()
    request, root, git, config, runtime, plan, guard = _prepare(
        request, repository_root, validate_apply, policy_version, verify_current, github)
    staged = single._object(staged, "bundle stage")

    def check():
        single._publication_remaining(deadline)
        guard()
        audit = _verify_branch(request, plan, root, git, config, staged)
        _producer(github, config, runtime, audit)
        single._publication_remaining(deadline)

    check()
    native = _fleet(staged["candidate"], fleet_receipt, verify_fleet)
    check()
    body = _body(config, staged, native)
    existing = publisher._one_owned_open_pull_request(config, single._all_prs(github, config))
    status = "unchanged" if existing else "created"

    def exact(pr):
        publisher._validate_pull_request_ownership(config, pr, expected_state="open")
        single._manual_review_only(pr)
        if (pr["head"]["sha"] != staged["candidate"]["candidate_sha"]
                or pr.get("body") != body or pr.get("title") != config.title
                or pr.get("html_url") != f"{config.repository_url}/pull/{publisher._pull_request_number(pr)}"):
            raise PublishError("bundle draft differs from the exact verified publication")

    if existing is not None:
        exact(existing)
        result = existing
    else:
        check()
        if single._all_prs(github, config):
            raise PublishError("bundle PR appeared during publication")
        _fleet(staged["candidate"], native, verify_fleet)
        check()
        result = github.create_pull_request(config, body=body, head_sha=staged["candidate"]["candidate_sha"])
        exact(result)
    verified = publisher._wait_for_exact_pull_request(
        config, github, expected_number=publisher._pull_request_number(result),
        expected_head_sha=staged["candidate"]["candidate_sha"], expected_body=body,
    )
    exact(verified)
    check()
    _fleet(staged["candidate"], native, verify_fleet)
    check()
    final = publisher._one_owned_open_pull_request(config, single._all_prs(github, config))
    if final is None or publisher._pull_request_number(final) != publisher._pull_request_number(verified):
        raise PublishError("bundle draft changed during final fleet verification")
    exact(final)
    single._publication_remaining(deadline)
    return {"status": status, "pr_url": final["html_url"], "candidate": staged["candidate"],
            "fleet_receipt_digest": _digest(native), "publisher": runtime}


def from_admission(admission):
    """Convert the bridge's authenticated shape without trusting it as authorization."""
    admission = single._object(admission, "cycle admission")
    if (set(admission) != {"schema_version", "request", "repairs"}
            or type(admission.get("schema_version")) is not int or admission["schema_version"] != 1):
        raise PublishError("unsupported cycle admission")
    from smoke_repair_cycle_bridge import validate_payload
    payload = single._object(admission["request"], "cycle dispatch")
    payload = validate_payload(payload, payload.get("base_sha"))
    return _request({"schema_version": 1,
                     **{key: payload[key] for key in ("repository", "base_sha", "cycle_id", "iteration")},
                     "packages": admission["repairs"]})


def export_receipt(admission, staged):
    request = from_admission(admission)
    staged = single._object(staged, "bundle stage")
    if set(staged) != {"candidate", "attestation"}:
        raise PublishError("unsupported bundle stage")
    descriptor = validate_descriptor(staged["candidate"])
    if any(descriptor[key] != value for key, value in _identity(request, _config(request)).items()):
        raise PublishError("exported stage differs from its admitted cycle")
    result = {"schema_version": 1, "admission": copy.deepcopy(admission), "staged": staged}
    _json(result)
    return result


def _envelope(value):
    receipt = single._object(value, "bundle receipt")
    if (set(receipt) != {"schema_version", "admission", "staged"}
            or type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1):
        raise PublishError("unsupported exported bundle receipt")
    if _json(export_receipt(receipt["admission"], receipt["staged"])) != _json(receipt):
        raise PublishError("bundle receipt is not canonical")
    return receipt


def _revalidate_admission(admission, api, root):
    # The bridge authenticates previous-iteration evidence as well as current
    # original failures. It must allow this exact already-created candidate.
    from smoke_repair_cycle_bridge import revalidate_admission
    session = session_for(api)
    now = session.wall_clock() if session is not None else datetime.now(timezone.utc)
    verified = revalidate_admission(copy.deepcopy(admission), api, root, now=now)
    if _json(verified) != _json(admission):
        raise PublishError("live cycle admission differs from the exported original evidence")
    return from_admission(verified)


def _controller_runtime(descriptor):
    repository, base = descriptor["repository"], descriptor["base_sha"]
    required = {
        "GITHUB_REPOSITORY": repository, "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": base, "GITHUB_WORKFLOW_SHA": base, "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": f"{repository}/.github/workflows/smoke-repair-cycle.yml@refs/heads/main",
        "GITHUB_EVENT_NAME": "repository_dispatch",
    }
    if any(os.environ.get(key) != value for key, value in required.items()):
        raise PublishError("bundle controller must execute the first-attempt trusted-main cycle workflow")


class _ReadOnlyGitHub:
    def __init__(self, api):
        self.api = api

    def _api(self, method, endpoint, payload=None):
        if method != "GET" or payload is not None:
            raise PublishError("fleet attestation cannot write to GitHub")
        return self.api.api(endpoint)


def attest_candidate(descriptor, bundle_receipt, *, api, repository_root):
    """Read-only bridge/policy/Git/App provenance revalidation for the fleet worker."""
    session = session_for(api)
    if session is not None:
        descriptor = validate_descriptor(descriptor)
        _controller_runtime(descriptor)
        envelope = _envelope(bundle_receipt)
        request = from_admission(envelope["admission"])
        root = Path(repository_root).resolve(strict=True)
        single._clean_base(root, publisher.Git(root), _config(request))
        identity = {"descriptor": descriptor, "bundle": bundle_receipt,
                    "app": os.environ.get("SMOKE_REPAIR_APP_BOT_LOGIN"),
                    "delivery_app": os.environ.get("DASHBOARD_DELIVERY_APP_BOT_LOGIN")}
        return session.verify("bundle-attestation", identity, api,
            lambda reader: _attest_candidate(descriptor, bundle_receipt, api=reader,
                                            repository_root=repository_root), root=repository_root)
    return _attest_candidate(descriptor, bundle_receipt, api=api, repository_root=repository_root)


def _attest_candidate(descriptor, bundle_receipt, *, api, repository_root):
    descriptor = validate_descriptor(descriptor)
    _controller_runtime(descriptor)
    if session_for(api) is not None:
        for branch, sha in (("main", descriptor["base_sha"]), (descriptor["branch"], descriptor["candidate_sha"])):
            validate_current_ref(api.api(f"repos/{descriptor['repository']}/git/ref/heads/{branch}"),
                                 expected_sha=sha, branch=branch)
    envelope = _envelope(bundle_receipt)
    if envelope["staged"]["candidate"] != descriptor:
        raise PublishError("fleet candidate differs from the exported publisher receipt")
    request = _revalidate_admission(envelope["admission"], api, repository_root)
    from smoke_repair_policy import POLICY_VERSION, validate_proposal
    root = Path(repository_root).resolve(strict=True)
    plan = readmit(request, repository_root=root, validate_apply=validate_proposal,
                   policy_version=str(POLICY_VERSION))
    login = os.environ.get("SMOKE_REPAIR_APP_BOT_LOGIN", "")
    generated_login = os.environ.get("DASHBOARD_DELIVERY_APP_BOT_LOGIN", "")
    publisher._validate_pr_credentials(login, "github-app")
    publisher._validate_pr_credentials(generated_login, "github-app")
    if login.casefold() == generated_login.casefold():
        raise PublishError("fleet attestor requires the dedicated repair App identity")
    config, git = _config(request, login), publisher.Git(root)
    single._clean_base(root, git, config)
    publisher._assert_remote_base_unchanged(git, config)
    audit = _verify_branch(request, plan, root, git, config, envelope["staged"])
    runtime = {"run_id": 1, "run_attempt": 1, "workflow_sha": request["base_sha"],
               "workflow_ref": f"{request['repository']}/.github/workflows/smoke-repair-cycle.yml@refs/heads/main",
               "app_bot_login": login}
    _producer(_ReadOnlyGitHub(api), config, runtime, audit)
    _revalidate_admission(envelope["admission"], api, root)
    publisher._assert_remote_base_unchanged(git, config)
    if publisher._remote_head_sha(git, config.head_branch) != descriptor["candidate_sha"]:
        raise PublishError("fleet candidate changed during attestation")
    return descriptor


def _load(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise PublishError("bundle input must be a bounded regular file")
    value = single.decode_json(path.read_bytes())
    _json(value)
    return value


def _output_directory(path, root):
    output = path.parent.resolve(strict=True) / path.name
    if output.is_relative_to(root.resolve()) or output.exists() or output.is_symlink():
        raise PublishError("bundle outputs must be new and outside the checkout")
    output.mkdir(mode=0o700)
    return output


def _write(path, value):
    raw = _json(value) + "\n"
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
        stream.write(raw)


def main(argv=None):
    from smoke_repair_upstream import ResearchError, research_session
    try:
        with research_session(metadata_token=os.environ.get("SMOKE_REPAIR_UPSTREAM_READ_TOKEN") or None) as research:
            return _main(argv, research=research)
    except ResearchError:
        print("upstream research initialization failed closed", file=sys.stderr)
        return 1


def _main(argv=None, *, research):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("readmit", "stage", "verify", "open-draft"))
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--admission", type=Path)
    parser.add_argument("--admitted", type=Path)
    parser.add_argument("--bundle-receipt", type=Path)
    parser.add_argument("--fleet-receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        from smoke_repair_policy import POLICY_VERSION, validate_proposal
        if args.mode in {"readmit", "stage"}:
            if args.admission is None or (args.mode == "stage" and args.admitted is None):
                raise PublishError("readmission/staging requires admission and staging requires admitted plan")
            admission = _load(args.admission)
            request = from_admission(admission)
            envelope = None
        else:
            if args.bundle_receipt is None:
                raise PublishError("verification/publication requires the exported bundle receipt")
            envelope = _envelope(_load(args.bundle_receipt))
            admission = envelope["admission"]
            request = from_admission(admission)
        if args.mode == "open-draft" and args.fleet_receipt is None:
            raise PublishError("publication requires full-fleet evidence")
        _controller_runtime(request)
        output = _output_directory(args.output_dir, args.repository_root)
        kwargs = {"repository_root": args.repository_root, "validate_apply": validate_proposal,
                  "policy_version": str(POLICY_VERSION)}
        if args.mode == "readmit":
            result = readmit(request, **kwargs)
            _write(output / "admitted.json", result)
        else:
            from smoke_repair_fleet import FleetValidation, VERIFY_SECONDS
            # Staging and verification also refresh the bounded ancestor fleet.
            deadline = time.monotonic() + VERIFY_SECONDS
            session = VerificationSession()
            fleet = FleetValidation(timeout_seconds=VERIFY_SECONDS, session=session)
            api = session.reader(fleet)
            def current(value):
                verified = _revalidate_admission(admission, api, args.repository_root)
                if _json(verified) != _json(value):
                    raise PublishError("current request differs from authenticated admission")
                return verified
            kwargs["verify_current"] = current
            if args.mode == "stage":
                research.refresh()
                staged = stage(request, _load(args.admitted), **kwargs)
                result = export_receipt(admission, staged)
                _write(output / "descriptor.json", staged["candidate"])
                _write(output / "bundle-receipt.json", result)
            elif args.mode == "verify":
                verify(request, envelope["staged"], **kwargs)
                result = envelope
                _write(output / "bundle-receipt.json", result)
            else:
                research.refresh()
                def verify_fleet(descriptor, receipt):
                    return fleet.verify(descriptor, receipt, repository_root=args.repository_root,
                                        bundle_receipt=envelope, attest_candidate=attest_candidate)
                result = open_draft(request, envelope["staged"], _load(args.fleet_receipt),
                                    verify_fleet=verify_fleet, deadline=deadline, **kwargs)
                _write(output / "publication.json", result)
                single._write_publication_outputs(result, request["repository"])
        print('{"status":"complete"}')
        return 0
    except Exception:
        print("bundle worker failed closed; no complete repair is claimed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
