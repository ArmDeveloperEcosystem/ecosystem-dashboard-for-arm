"""Authenticate cumulative multi-package repair requests on trusted public main.

Every iteration is independently admitted against the original reviewed source.
Previous public failure evidence is a prerequisite for another iteration, not
authority supplied by the model. This module never executes proposed code.
"""

from __future__ import annotations

from copy import deepcopy
import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestration_contract import ContractError, decode_json, validate_current_ref, validate_sha
from exact_run_aggregation import _prevalidate_zip_directory
from smoke_recovery import GitHub, timestamp
from smoke_repair_evidence import complete_jobs, read_json, write_json
from smoke_repair_session import VerificationSession, session_for
from smoke_repair_bridge import (
    REPOSITORY, authenticate_contexts, compile_proposal, context_digest, integer,
    validate_operations, validate_sender,
)

WORKFLOW = ".github/workflows/smoke-repair-cycle.yml"
EVENT = "smoke-repair-cycle-proposal"
MAX_ITERATIONS = 3
ADMISSION_SECONDS = 75 * 60
MAX_PACKAGES = 10
MAX_FEEDBACK_BYTES = 16 * 1024 * 1024
FEEDBACK_JOB = "Validate complete repair candidate on hosted Arm"
NATIVE_STEP = "Run complete candidate fleet and build candidate summary"
FEEDBACK_STEPS = {NATIVE_STEP, "Preserve authenticated cycle feedback"}
PAYLOAD_KEYS = {
    "schema_version", "repository", "base_sha", "orchestrator_run_id",
    "orchestrator_attempt", "context_artifact_id", "cycle_id", "iteration",
    "previous_feedback_run_id", "previous_feedback_artifact_id", "proposals",
}
PROPOSAL_KEYS = {"package_slug", "context_sha256", "operations"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def proposal_digest(proposals):
    return hashlib.sha256(canonical(proposals).encode("utf-8")).hexdigest()


def candidate_branch(cycle_id, iteration):
    if not isinstance(cycle_id, str) or not re.fullmatch(r"[1-9][0-9]{0,18}-[1-9][0-9]{0,8}", cycle_id):
        raise ContractError("repair cycle identity is invalid")
    integer(iteration, 1, MAX_ITERATIONS)
    return f"automation/smoke-repair-cycle/{cycle_id}/iteration-{iteration}"


def validate_payload(payload, sha):
    validate_sha(sha)
    if type(payload) is not dict or set(payload) != PAYLOAD_KEYS:
        raise ContractError("repair cycle callback fields are invalid")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 2:
        raise ContractError("repair cycle callback schema is invalid")
    if payload["repository"] != REPOSITORY or payload["base_sha"] != sha:
        raise ContractError("repair cycle belongs to a different repository or main commit")
    for field in ("orchestrator_run_id", "orchestrator_attempt", "context_artifact_id"):
        integer(payload[field], 1, 10**19 - 1)
    if payload["cycle_id"] != f"{payload['orchestrator_run_id']}-{payload['orchestrator_attempt']}":
        raise ContractError("repair cycle is not bound to its original orchestration")
    candidate_branch(payload["cycle_id"], payload["iteration"])
    for field in ("previous_feedback_run_id", "previous_feedback_artifact_id"):
        if payload["iteration"] == 1:
            if payload[field] is not None:
                raise ContractError("first repair iteration cannot claim previous candidate evidence")
        else:
            integer(payload[field], 1, 10**19 - 1)
    proposals = payload["proposals"]
    if type(proposals) is not list or not 1 <= len(proposals) <= MAX_PACKAGES:
        raise ContractError("repair cycle requires a bounded nonempty proposal inventory")
    slugs = []
    for proposal in proposals:
        if type(proposal) is not dict or set(proposal) != PROPOSAL_KEYS:
            raise ContractError("repair package proposal fields are invalid")
        slug = proposal["package_slug"]
        if type(slug) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", slug):
            raise ContractError("repair cycle package is invalid")
        if type(proposal["context_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", proposal["context_sha256"]):
            raise ContractError("repair cycle context digest is invalid")
        validate_operations(proposal["operations"])
        slugs.append(slug)
    if slugs != sorted(set(slugs)):
        raise ContractError("repair cycle package inventory must be unique and sorted")
    if len(canonical(payload).encode("utf-8")) >= 60 * 1024:
        raise ContractError("repair cycle callback exceeds the dispatch budget")
    return deepcopy(payload)


def validate_event(event, environment):
    sha = validate_sender(event, environment, workflow=WORKFLOW, event_type=EVENT)
    transport = event.get("client_payload")
    # repository_dispatch permits at most ten top-level client_payload fields.
    if type(transport) is not dict or set(transport) != {"repair"}:
        raise ContractError("repair cycle transport must contain only the repair document")
    return validate_payload(transport["repair"], sha)


def read_feedback_document(payload, api, *, now):
    """Authenticate a prior public controller artifact before inspecting its data."""
    run_id = integer(payload["previous_feedback_run_id"], 1, 10**19 - 1)
    artifact_id = integer(payload["previous_feedback_artifact_id"], 1, 10**19 - 1)
    endpoint = f"repos/{REPOSITORY}/actions/runs/{run_id}"
    run = api.api(endpoint)
    expected = {"id": run_id, "run_attempt": 1, "event": "repository_dispatch",
                "head_branch": "main", "head_sha": payload["base_sha"], "path": WORKFLOW,
                "status": "completed", "conclusion": "failure"}
    if (type(run) is not dict or type(run.get("id")) is not int
            or type(run.get("run_attempt")) is not int
            or any(run.get(key) != value for key, value in expected.items())
            or any(type(run.get(field)) is not dict or run[field].get("full_name") != REPOSITORY
                   for field in ("repository", "head_repository"))
            or not 0 <= now - timestamp(run.get("created_at")).timestamp() <= 72 * 60 * 60):
        raise ContractError("previous repair run is not a fresh exact failed controller")
    jobs = complete_jobs(api.api(endpoint + "/attempts/1/jobs?per_page=100", pages=True))
    matches = [job for job in jobs if job.get("name") == FEEDBACK_JOB]
    if len(matches) != 1:
        raise ContractError("previous feedback producer is missing or duplicated")
    job = matches[0]
    if (type(job.get("run_id")) is not int or type(job.get("run_attempt")) is not int
            or any(job.get(key) != value for key, value in {
                "run_id": run_id, "run_attempt": 1, "head_sha": payload["base_sha"],
                "status": "completed", "conclusion": "failure"}.items())):
        raise ContractError("previous feedback producer has invalid identity")
    steps = job.get("steps")
    if type(steps) is not list or any(type(step) is not dict for step in steps):
        raise ContractError("previous feedback producer steps are malformed")
    for name in FEEDBACK_STEPS:
        selected = [step for step in steps if step.get("name") == name]
        if len(selected) != 1 or selected[0].get("status") != "completed" or selected[0].get("conclusion") != "success":
            raise ContractError("previous feedback lacks completed evidence collection")
    from smoke_repair_bridge import artifact_inventory
    name = f"smoke-repair-cycle-feedback-{payload['cycle_id']}-{payload['iteration'] - 1}"
    matches = [item for item in artifact_inventory(api, run_id) if item.get("name") == name]
    if len(matches) != 1 or matches[0].get("id") != artifact_id:
        raise ContractError("previous feedback artifact is absent or ambiguous")
    artifact = matches[0]
    origin = artifact.get("workflow_run")
    size = integer(artifact.get("size_in_bytes"), 1, MAX_FEEDBACK_BYTES)
    if (artifact.get("expired") is not False or type(origin) is not dict
            or type(origin.get("id")) is not int
            or any(origin.get(key) != value for key, value in {
                "id": run_id, "head_sha": payload["base_sha"], "head_branch": "main"}.items())
            or not timestamp(job.get("started_at")) <= timestamp(artifact.get("created_at")) <= timestamp(job.get("completed_at"))):
        raise ContractError("previous feedback artifact provenance is invalid")
    raw = api.api(f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip", raw=True)
    if (type(raw) is not bytes or len(raw) != size
            or artifact.get("digest") != "sha256:" + hashlib.sha256(raw).hexdigest()):
        raise ContractError("previous feedback artifact digest is invalid")
    _prevalidate_zip_directory(raw)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise ContractError("feedback archive must contain one bounded JSON document")
            entry = entries[0]
            if (entry.filename != "feedback.json" or entry.is_dir() or entry.flag_bits & 1
                    or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                    or not 0 < entry.file_size <= MAX_FEEDBACK_BYTES):
                raise ContractError("feedback archive member is unsafe")
            with archive.open(entry) as stream:
                data = stream.read(MAX_FEEDBACK_BYTES + 1)
            if len(data) != entry.file_size:
                raise ContractError("feedback document is truncated")
            document = decode_json(data)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ContractError("feedback archive cannot be read") from exc
    fresh = api.api(endpoint)
    if type(fresh) is not dict or any(fresh.get(key) != value for key, value in expected.items()):
        raise ContractError("previous repair run changed while reading evidence")
    return document


def admit_cycle(payload, api, root, *, now, verify_previous=None, revalidation=False, session=None):
    session = session_for(api, session)
    now = now.timestamp() if isinstance(now, datetime) else now
    if session is not None:
        return session.verify("cycle-admission", {"payload": payload, "revalidation": revalidation}, api,
            lambda reader: _admit_cycle(payload, reader, root, now=now,
                verify_previous=verify_previous, revalidation=revalidation), root=root, now=now)
    return _admit_cycle(payload, api, root, now=now,
                        verify_previous=verify_previous, revalidation=revalidation)


def _admit_cycle(payload, api, root, *, now, verify_previous=None, revalidation=False):
    """Return source-bound proposals; a live verifier must admit retry evidence."""
    if type(payload) is not dict:
        raise ContractError("repair cycle callback must be an object")
    now = now.timestamp() if isinstance(now, datetime) else now
    payload = validate_payload(payload, payload.get("base_sha"))
    session = session_for(api)
    if session is None:
        contexts = authenticate_contexts(payload, api, root, now=now)
    else:
        original = {key: payload[key] for key in ("repository", "base_sha", "orchestrator_run_id",
                                                "orchestrator_attempt", "context_artifact_id")}
        contexts = session.verify("original-contexts", original, api,
            lambda reader: authenticate_contexts(payload, reader, root, now=now), root=root, now=now,
            run_ages={f"repos/{REPOSITORY}/actions/runs/{payload['orchestrator_run_id']}": 72 * 60 * 60})
    if payload["iteration"] > 1:
        if verify_previous is None:
            raise ContractError("a fresh iteration requires independent live failure verification")
        previous = verify_previous(payload, api, root, now=now)
        if (type(previous) is not dict or previous.get("status") != "failed"
                or previous.get("cycle_id") != payload["cycle_id"]
                or previous.get("base_sha") != payload["base_sha"]
                or type(previous.get("iteration")) is not int
                or previous["iteration"] != payload["iteration"] - 1
                or type(previous.get("proposal_digest")) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", previous["proposal_digest"])
                or previous.get("proposal_digest") == proposal_digest(payload["proposals"])):
            raise ContractError("previous iteration does not authorize this revised candidate")
        if "contexts" in previous:
            prior_contexts = previous["contexts"]
            original = {item["package_slug"]: item for item in contexts}
            if (type(prior_contexts) is not list or not 1 <= len(prior_contexts) <= MAX_PACKAGES
                    or any(type(item) is not dict for item in prior_contexts)):
                raise ContractError("previous iteration context inventory is invalid")
            prior = {item.get("package_slug"): item for item in prior_contexts}
            if (len(prior) != len(prior_contexts)
                    or any(prior.get(slug) != context for slug, context in original.items())):
                raise ContractError("previous iteration replaced original failure contexts")
            contexts = prior_contexts
    by_slug = {item["package_slug"]: item for item in contexts}
    if set(by_slug) != {item["package_slug"] for item in payload["proposals"]}:
        raise ContractError("repair proposal does not cover the complete authenticated incident")
    branch = candidate_branch(payload["cycle_id"], payload["iteration"])
    if not revalidation:
        references = api.api(f"repos/{REPOSITORY}/git/matching-refs/heads/{branch}")
        pulls = api.api(f"repos/{REPOSITORY}/pulls?state=all&head=ArmDeveloperEcosystem:{branch}&per_page=100")
        if (type(references) is not list or any(type(item) is not dict or type(item.get("ref")) is not str for item in references)
                or any(item["ref"] == f"refs/heads/{branch}" for item in references)
                or type(pulls) is not list or pulls):
            raise ContractError("repair iteration already exists or its reference inventory is invalid")
    admitted = []
    for proposal in payload["proposals"]:
        context = by_slug[proposal["package_slug"]]
        if context_digest(context) != proposal["context_sha256"]:
            raise ContractError("repair operation is bound to different original failure evidence")
        admitted.append({"context": context,
                         "proposal": compile_proposal(context, proposal["operations"])})
    validate_current_ref(api.api(f"repos/{REPOSITORY}/git/ref/heads/main"),
                         expected_sha=payload["base_sha"], branch="main")
    return {"schema_version": 1, "request": payload, "repairs": admitted}


def verify_previous_feedback(payload, api, root, *, now):
    """Rebuild preceding fleet results from GitHub, never from model assertions."""
    session = session_for(api)
    if session is not None:
        identity = {key: payload[key] for key in PAYLOAD_KEYS - {"proposals"}}
        return session.verify("previous-feedback", identity, api,
            lambda reader: _verify_previous_feedback(payload, reader, root, now=now), root=root, now=now,
            run_ages={f"repos/{REPOSITORY}/actions/runs/{payload['previous_feedback_run_id']}": 72 * 60 * 60})
    return _verify_previous_feedback(payload, api, root, now=now)


def _verify_previous_feedback(payload, api, root, *, now):
    from smoke_repair_bundle import attest_candidate
    from smoke_repair_fleet import FleetValidation
    document = read_feedback_document(payload, api, now=now)
    if (type(document) is not dict or set(document) != {"schema_version", "bundle_receipt", "fleet_receipt", "contexts"}
            or type(document.get("schema_version")) is not int or document["schema_version"] != 1):
        raise ContractError("previous feedback envelope is invalid")
    bundle, receipt = document["bundle_receipt"], document["fleet_receipt"]
    if type(bundle) is not dict or type(receipt) is not dict:
        raise ContractError("previous feedback receipts are invalid")
    admission = bundle.get("admission")
    if type(admission) is not dict or type(admission.get("request")) is not dict:
        raise ContractError("previous feedback has no original admission")
    previous = validate_payload(admission["request"], payload["base_sha"])
    keys = ("repository", "base_sha", "orchestrator_run_id", "orchestrator_attempt",
            "context_artifact_id", "cycle_id")
    if (any(previous[key] != payload[key] for key in keys)
            or previous["iteration"] != payload["iteration"] - 1):
        raise ContractError("previous feedback belongs to a different repair cycle")
    staged = bundle.get("staged")
    if type(staged) is not dict or type(staged.get("candidate")) is not dict:
        raise ContractError("previous feedback candidate is invalid")
    descriptor = staged["candidate"]
    if (descriptor.get("cycle_id") != payload["cycle_id"]
            or descriptor.get("iteration") != previous["iteration"]
            or descriptor.get("base_sha") != payload["base_sha"]):
        raise ContractError("previous feedback candidate identity differs")
    result = FleetValidation.verifier(api, now=now).verify(
        descriptor, receipt, repository_root=root, bundle_receipt=bundle,
        attest_candidate=attest_candidate)
    if result["status"] != "failure":
        raise ContractError("only authenticated failed fleet evidence permits another repair")
    from smoke_repair_cycle_context import expand_contexts
    contexts = expand_contexts(admission, result, root, api)
    if canonical(contexts) != canonical(document["contexts"]):
        raise ContractError("previous context expansion differs from authenticated fleet failures")
    return {"status": "failed", "cycle_id": previous["cycle_id"], "base_sha": previous["base_sha"],
            "iteration": previous["iteration"], "proposal_digest": proposal_digest(previous["proposals"]),
            "contexts": contexts}


def revalidate_admission(admission, api, root, *, now, session=None):
    """Recheck evidence only; the publisher separately attests any staged branch."""
    if (type(admission) is not dict or set(admission) != {"schema_version", "request", "repairs"}
            or type(admission.get("schema_version")) is not int or admission["schema_version"] != 1):
        raise ContractError("repair admission envelope is invalid")
    verified = admit_cycle(admission["request"], api, root, now=now,
                           verify_previous=verify_previous_feedback, revalidation=True,
                           session=session)
    if canonical(verified) != canonical(admission):
        raise ContractError("repair admission differs from independently authenticated source")
    return verified


def _native_origin(envelope, receipt, api, *, now):
    """Bind local packaging to the successful native step in this controller.

    This is not reusable evidence authorization. The trusted-main job reads
    only its fixed local outputs; downstream consumers still verify the fleet.
    """
    from smoke_repair_bundle import ATTESTATION_KEYS, _controller_runtime
    from smoke_repair_fleet import MAX_SECONDS
    descriptor = envelope["staged"]["candidate"]
    _controller_runtime(descriptor)
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if os.environ.get("GITHUB_JOB") != "native" or not re.fullmatch(r"[1-9][0-9]{0,18}", run_id):
        raise ContractError("native packaging requires the current controller run")
    audit = envelope["staged"]["attestation"]
    if (type(audit) is not dict or set(audit) != ATTESTATION_KEYS
            or type(audit.get("schema_version")) is not int or audit["schema_version"] != 1
            or type(receipt) is not dict):
        raise ContractError("local native receipt or publisher envelope is malformed")
    producer = audit["publisher"]
    expected = {"run_id": int(run_id), "run_attempt": 1,
        "workflow_sha": descriptor["base_sha"],
        "workflow_ref": f"{REPOSITORY}/{WORKFLOW}@refs/heads/main",
        "app_bot_login": os.environ.get("SMOKE_REPAIR_APP_BOT_LOGIN")}
    if canonical(producer) != canonical(expected) or not expected["app_bot_login"]:
        raise ContractError("local receipt was not staged by this first-attempt controller")
    endpoint = f"repos/{REPOSITORY}/actions/runs/{run_id}"
    run = api.api(endpoint)
    identity = {"id": int(run_id), "run_attempt": 1, "event": "repository_dispatch",
        "head_branch": "main", "head_sha": descriptor["base_sha"], "path": WORKFLOW,
        "status": "in_progress", "conclusion": None}
    if (type(run) is not dict or type(run.get("id")) is not int
            or type(run.get("run_attempt")) is not int
            or any(run.get(key) != value for key, value in identity.items())
            or any(type(run.get(key)) is not dict or run[key].get("full_name") != REPOSITORY
                   for key in ("repository", "head_repository"))):
        raise ContractError("native packaging controller is no longer the current first attempt")
    jobs = complete_jobs(api.api(endpoint + "/attempts/1/jobs?per_page=100", pages=True))
    matches = [job for job in jobs if job.get("name") == FEEDBACK_JOB]
    if len(matches) != 1:
        raise ContractError("local native producer is missing or duplicated")
    job = matches[0]
    expected_job = {"run_id": int(run_id), "run_attempt": 1, "head_sha": descriptor["base_sha"],
        "status": "in_progress", "conclusion": None}
    if (type(job.get("run_id")) is not int or type(job.get("run_attempt")) is not int
            or any(job.get(key) != value for key, value in expected_job.items())):
        raise ContractError("local native job does not satisfy the packaging boundary")
    steps = job.get("steps")
    if type(steps) is not list or any(type(step) is not dict for step in steps):
        raise ContractError("local native job steps are malformed")
    for name in (NATIVE_STEP,):
        selected = [step for step in steps if step.get("name") == name]
        if len(selected) != 1 or selected[0].get("status") != "completed" or selected[0].get("conclusion") != "success":
            raise ContractError("local native evidence collection did not succeed")
    step = next(step for step in steps if step.get("name") == NATIVE_STEP)
    started, completed = timestamp(receipt.get("started_at")), timestamp(receipt.get("completed_at"))
    if (not timestamp(run.get("created_at")) <= timestamp(job.get("started_at"))
            <= timestamp(step.get("started_at")) <= started <= completed
            <= timestamp(step.get("completed_at"))
            or timestamp(step.get("completed_at")).timestamp() > now
            or not 0 <= now - started.timestamp() <= 86400
            or (completed - started).total_seconds() > MAX_SECONDS):
        raise ContractError("local receipt is outside the successful native step")


def package_feedback(bundle, receipt, root, api, *, now=None):
    """Package trusted local native output, never authorize downloaded feedback.

    Only the current controller's native job may use this path. No candidate
    code runs in this workspace.
    Retry admission and App publication independently verify every artifact.
    """
    from smoke_repair_bundle import _envelope, from_admission, _config, single, publisher
    from smoke_repair_cycle_context import expand_contexts
    from smoke_repair_fleet import validate_local_receipt
    envelope = _envelope(bundle)
    root = Path(root).resolve(strict=True)
    single._clean_base(root, publisher.Git(root), _config(from_admission(envelope["admission"])))
    clock = time.time if now is None else lambda: now
    _native_origin(envelope, receipt, api, now=clock())
    # The preceding successful native step performed live validation. Here the
    # source/shape/ref checks only prepare data for independent later admission.
    contexts = expand_contexts(envelope["admission"], receipt, root, api)
    validate_local_receipt(envelope["staged"]["candidate"], receipt, repository_root=root)
    _native_origin(envelope, receipt, api, now=clock())
    return {"schema_version": 1, "bundle_receipt": envelope, "fleet_receipt": receipt,
            "contexts": contexts}


def main(argv=None):
    from smoke_repair_upstream import ResearchError, research_session
    try:
        with research_session(metadata_token=os.environ.get("SMOKE_REPAIR_UPSTREAM_READ_TOKEN") or None) as research:
            research.refresh()
            return _main(argv)
    except ResearchError:
        print("upstream research initialization failed closed", file=sys.stderr)
        return 1


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("admit", "feedback", "enforce"))
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--event", type=Path)
    parser.add_argument("--bundle-receipt", type=Path)
    parser.add_argument("--fleet-receipt", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "admit":
            from smoke_repair_fleet import FleetValidation
            event = args.event or Path(os.environ["GITHUB_EVENT_PATH"])
            payload = validate_event(read_json(event), os.environ)
            # One quota reset plus bounded verification, before any write token.
            session = VerificationSession()
            api = FleetValidation(timeout_seconds=ADMISSION_SECONDS, session=session)
            result = admit_cycle(payload, api, args.repository_root,
                                 now=time.time(), verify_previous=verify_previous_feedback)
            filename = "admission.json"
        else:
            if args.bundle_receipt is None or args.fleet_receipt is None:
                raise ContractError("candidate evaluation requires both exact receipts")
            bundle, receipt = read_json(args.bundle_receipt), read_json(args.fleet_receipt)
            from smoke_repair_fleet import validate_descriptor
            descriptor = validate_descriptor(bundle["staged"]["candidate"])
            if args.mode == "enforce":
                # This gate follows successful live verification in the same
                # trusted-main job; publication independently verifies again.
                if (receipt.get("descriptor") != descriptor or receipt.get("publishing") is not False
                        or receipt.get("kind") != "smoke-repair-candidate-fleet"):
                    raise ContractError("success gate does not match the verified candidate")
                return 0 if receipt.get("status") == "success" else 1
            result = package_feedback(bundle, receipt, args.repository_root, GitHub(time.monotonic() + 300))
            filename = "feedback.json"
        if args.output_dir is None:
            raise ContractError("output directory is required")
        args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        write_json(args.output_dir / filename, result)
        print(canonical({"status": "packaged" if args.mode == "feedback" else "verified", "publishing": False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError):
        print("repair cycle validation failed closed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
