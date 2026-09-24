"""Expand a verified cumulative repair incident using original-base source only.

The caller must first authenticate the admission and run FleetValidation.verify
on the complete receipt. This helper is not a replacement for those trust gates.
Persist its result as feedback.contexts, then recompute and compare that field
when consuming feedback. No model/callback-supplied source is authoritative.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from exact_run_aggregation import discover_topology_at_commit, expected_job_name
from orchestration_contract import ContractError, canonical_json, validate_current_ref, validate_run
from smoke_repair_bridge import context_digest
from smoke_repair_evidence import failed_step_names, read_source
from smoke_repair_fleet import REPOSITORY, RECEIPT_KEYS, validate_descriptor
from smoke_repair_publisher import CONTEXT_KEYS, PublishError, _context

MAX_CONTEXTS = 10
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
OBSERVATION_KEYS = {"package_slug", "workflow_path", "batch", "run_id", "run_attempt", "job_id", "job_url", "status", "required_steps"}
HISTORY_KEYS = {"batch", "run_id", "run_attempt", "dispatch_nonce", "status", "artifact_status", "record", "observations"}


def _require(condition, reason):
    if not condition:
        raise ContractError(f"repair context expansion requires manual investigation: {reason}")


def _positive(value):
    _require(type(value) is int and 0 < value < 2**63, "invalid evidence identity")
    return value


def _current(api, descriptor):
    for branch, sha in (("main", descriptor["base_sha"]), (descriptor["branch"], descriptor["candidate_sha"])):
        validate_current_ref(api.api(f"repos/{REPOSITORY}/git/ref/heads/{branch}"), expected_sha=sha, branch=branch)


def _original_contexts(admission, descriptor, root, registrations):
    from smoke_repair_cycle_bridge import validate_payload

    _require(type(admission) is dict and set(admission) == {"schema_version", "request", "repairs"}
             and type(admission.get("schema_version")) is int and admission["schema_version"] == 1,
             "unsupported admission envelope")
    request = validate_payload(admission["request"], descriptor["base_sha"])
    _require(all(request[key] == descriptor[key] for key in ("repository", "base_sha", "cycle_id", "iteration")),
             "admission and candidate identities differ")
    repairs = admission["repairs"]
    _require(type(repairs) is list and 1 <= len(repairs) <= MAX_CONTEXTS, "incident exceeds context budget")
    contexts = {}
    for repair in repairs:
        _require(type(repair) is dict and set(repair) == {"context", "proposal"}, "unsupported admitted repair")
        try:
            context = _context(repair["context"])
        except (PublishError, TypeError, ValueError) as exc:
            raise ContractError("repair context expansion requires manual investigation: invalid original context") from exc
        slug = context["package_slug"]
        _require(slug not in contexts and slug in registrations, "duplicate or unregistered original package")
        batch, registration = registrations[slug]
        expected = {"repository": REPOSITORY, "base_sha": descriptor["base_sha"],
            "orchestration_id": f"orchestration-{descriptor['cycle_id']}",
            "orchestrator_run_id": request["orchestrator_run_id"],
            "orchestrator_run_attempt": request["orchestrator_attempt"], "batch": batch.batch,
            "workflow_path": registration.workflow_path, "called_job": registration.called_job}
        _require(all(context[key] == value for key, value in expected.items()), "original context binding differs")
        # A supplied source never replaces Git evidence. Mismatch is a blocker,
        # not a silent rewrite that would change an already-authenticated digest.
        source = read_source(root, descriptor["base_sha"], registration.workflow_path)
        _require(context["source_text"] == source, "original context source differs from reviewed base")
        contexts[slug] = context
    proposals = request["proposals"]
    _require(set(contexts) == {p["package_slug"] for p in proposals}, "admitted package inventory differs")
    for proposal in proposals:
        _require(context_digest(contexts[proposal["package_slug"]]) == proposal["context_sha256"],
                 "original context digest differs")
    return request, contexts


def _receipt_failures(receipt, descriptor, topology):
    _require(type(receipt) is dict and set(receipt) == RECEIPT_KEYS
             and type(receipt.get("schema_version")) is int and receipt["schema_version"] == 1
             and receipt.get("kind") == "smoke-repair-candidate-fleet" and receipt.get("publishing") is False
             and receipt.get("status") in {"success", "failure"}, "unsupported verified fleet receipt")
    _require(receipt["descriptor"] == descriptor, "fleet descriptor differs")
    summary = receipt["summary"]
    _require(type(summary) is dict and summary.get("kind") == "candidate-global-summary"
             and summary.get("publishing") is False and summary.get("evidence_status") == "complete"
             and summary.get("candidate_sha") == descriptor["candidate_sha"]
             and summary.get("status") == receipt["status"], "fleet evidence is not complete")
    history = receipt["history"]
    _require(type(history) is list and len(history) == len(topology), "incomplete registered batch inventory")
    selected, failed_batches, accepted, by_slug = [], [], [], {}
    run_ids, job_ids, nonces = set(), set(), set()
    for batch, attempts in zip(topology, history, strict=True):
        _require(type(attempts) is list and 1 <= len(attempts) <= 2, "invalid batch confirmation inventory")
        for index, entry in enumerate(attempts):
            _require(type(entry) is dict and set(entry) == HISTORY_KEYS, "unsupported batch observation")
            run_id = _positive(entry["run_id"])
            nonce = entry["dispatch_nonce"]
            _require(type(nonce) is str and re.fullmatch(r"[0-9a-f]{64}", nonce)
                     and nonce not in nonces and run_id not in run_ids, "reused or malformed dispatch identity")
            nonces.add(nonce)
            run_ids.add(run_id)
            _require(type(entry["batch"]) is int and entry["batch"] == batch.batch
                     and type(entry["run_attempt"]) is int and entry["run_attempt"] == 1
                     and entry["status"] in {"success", "failure"}
                     and entry["artifact_status"] in {"verified", "missing", "collector_failed"},
                     "batch identity or artifact verification differs")
            observations = entry["observations"]
            _require(type(observations) is list and len(observations) == len(batch.packages),
                     "incomplete registered package inventory")
            record = entry["record"]
            verified_artifact = entry["artifact_status"] == "verified"
            if verified_artifact:
                _require(type(record) is dict and type(record.get("run")) is dict
                         and record["run"].get("id") == run_id and record["run"].get("attempt") == 1
                         and record["run"].get("head_sha") == descriptor["candidate_sha"]
                         and record["run"].get("head_branch") == descriptor["branch"]
                         and record["run"].get("conclusion") == entry["status"]
                         and type(record.get("jobs")) is list and len(record["jobs"]) == len(batch.packages),
                         "batch manifest binding differs")
                jobs = record["jobs"]
            else:
                # A verified recovery may retain negative API observations from
                # an initial collector failure. No artifact is invented for it.
                _require(index == 0 and len(attempts) == 2 and entry["status"] == "failure" and record is None
                         and type(attempts[-1]) is dict
                         and attempts[-1].get("status") == "success"
                         and attempts[-1].get("artifact_status") == "verified",
                         "incomplete initial artifact cannot authorize another package repair")
                jobs = [None] * len(batch.packages)
            for registration, observation, job in zip(batch.packages, observations, jobs, strict=True):
                _require(type(observation) is dict and set(observation) == OBSERVATION_KEYS,
                         "unsupported package observation")
                job_id = _positive(observation["job_id"])
                _require(job_id not in job_ids, "reused package job identity")
                job_ids.add(job_id)
                expected = {"package_slug": registration.package_slug, "workflow_path": registration.workflow_path,
                    "batch": batch.batch, "run_id": run_id, "run_attempt": 1,
                    "job_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/job/{job_id}"}
                _require(all(observation.get(key) == value for key, value in expected.items())
                         and observation.get("status") in {"success", "failure"}
                         and type(observation.get("run_attempt")) is int,
                         "package observation identity differs")
                if verified_artifact:
                    _require(type(job) is dict and job.get("id") == job_id and job.get("run_id") == run_id and job.get("run_attempt") == 1
                             and job.get("name") == expected_job_name(registration)
                             and job.get("conclusion") == observation["status"], "manifest package job differs")
        if len(attempts) == 2:
            _require(attempts[0]["status"] == "failure", "passing batch was retried")
        final = attempts[-1]
        if final["status"] == "failure":
            _require(len(attempts) == 2, "failed batch has no distinct confirmation")
            failed_batches.append(batch.batch)
        accepted.append({"batch": batch.batch, "run_id": final["run_id"], "run_attempt": 1, "status": final["status"]})
        selected.extend(final["observations"])
        for first, last in zip(attempts[0]["observations"], final["observations"], strict=True):
            if last["status"] == "failure":
                _require(final["status"] == "failure", "failed package hidden by passing batch")
                by_slug[last["package_slug"]] = (attempts[0], final, first, last)
    failed = [o for o in selected if o["status"] == "failure"]
    _require(summary.get("failed_packages") == failed and summary.get("failed_batches") == failed_batches
             and summary.get("accepted_runs") == accepted and summary.get("batch_count") == len(topology)
             and summary.get("package_count") == len(selected)
             and summary.get("passed_packages") == sum(o["status"] == "success" for o in selected),
             "candidate summary does not cover exact selected observations")
    _require(receipt["status"] == ("failure" if failed_batches else "success"), "fleet verdict contradicts history")
    return by_slug


def _live_run(api, descriptor, batch, entry):
    run_id = entry["run_id"]
    run = api.api(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    validate_run(run, batch=batch.batch, orchestration_id=f"orchestration-{descriptor['cycle_id']}",
        dispatch_nonce=entry["dispatch_nonce"], expected_sha=descriptor["candidate_sha"],
        branch=descriptor["branch"], repository=REPOSITORY, expected_run_id=run_id, require_completed=True)
    _require(run.get("conclusion") == "failure" and type(run.get("head_repository")) is dict
             and run["head_repository"].get("full_name") == REPOSITORY,
             "candidate confirmation run changed or belongs to another repository")


def _live_failed_steps(api, descriptor, registration, observation):
    job_id, run_id = observation["job_id"], observation["run_id"]
    job = api.api(f"repos/{REPOSITORY}/actions/jobs/{job_id}")
    expected = {"id": job_id, "run_id": run_id, "run_attempt": 1, "head_sha": descriptor["candidate_sha"],
        "head_branch": descriptor["branch"], "name": expected_job_name(registration),
        "status": "completed", "conclusion": "failure", "labels": ["ubuntu-24.04-arm"],
        "runner_group_id": 0, "runner_group_name": "GitHub Actions", "html_url": observation["job_url"],
        "url": f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{job_id}",
        "run_url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}"}
    _require(type(job) is dict and all(job.get(key) == value for key, value in expected.items()),
             "live failed package job differs from verified receipt")
    for field in ("id", "run_id", "run_attempt", "runner_id"):
        _positive(job.get(field))
    _require(type(job.get("runner_group_id")) is int, "unverified hosted runner identity")
    steps = observation.get("required_steps")
    _require(type(steps) is list and 6 <= len(steps) <= 7, "required probe inventory is unsupported")
    failed = failed_step_names(job)
    _require(len(job["steps"]) <= 200 and all(len(name) <= 512 and not any(ord(c) < 32 for c in name) for name in failed),
             "failed step inventory is unbounded")
    for step in steps:
        _require(type(step) is dict and set(step) == {"number", "name", "conclusion"}, "invalid required probe observation")
        matches = [live for live in job["steps"] if live["number"] == step["number"]
                   and (step["name"] is None or live["name"] == step["name"])]
        _require(len(matches) == 1 and matches[0]["conclusion"] == step["conclusion"],
                 "live failed probes changed after fleet verification")
    return failed


def expand_contexts(admission, verified_receipt, root, api):
    """Return sorted cumulative contexts after independent full-fleet verification.

    Existing contexts are returned byte-for-byte equivalent, including their
    original failure identities and log excerpts. Only newly confirmed failures
    get new evidence identities. Source always remains bound to original main.
    """
    _require(type(verified_receipt) is dict, "fleet receipt is not an object")
    try:
        _require(len(canonical_json(verified_receipt).encode("utf-8")) <= MAX_DOCUMENT_BYTES,
                 "fleet receipt exceeds the bounded feedback budget")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError("repair context expansion requires manual investigation: malformed receipt") from exc
    descriptor = validate_descriptor(verified_receipt.get("descriptor"))
    _current(api, descriptor)
    root = Path(root)
    topology = discover_topology_at_commit(root, descriptor["base_sha"])
    registrations = {p.package_slug: (batch, p) for batch in topology for p in batch.packages}
    request, contexts = _original_contexts(admission, descriptor, root, registrations)
    failures = _receipt_failures(verified_receipt, descriptor, topology)
    new_slugs = sorted(set(failures) - set(contexts))
    _require(len(contexts) + len(new_slugs) <= MAX_CONTEXTS, "cumulative failures exceed the ten-package repair budget")
    for slug in new_slugs:
        first_entry, final_entry, first, final = failures[slug]
        _require(first["status"] == "failure" and first["run_id"] != final["run_id"],
                 "new package failure was not reproduced in both exact runs")
    runs = {}
    for slug in new_slugs:
        batch, registration = registrations[slug]
        first_entry, final_entry, first, final = failures[slug]
        for entry in (first_entry, final_entry):
            if entry["run_id"] not in runs:
                _live_run(api, descriptor, batch, entry)
                runs[entry["run_id"]] = (batch, entry)
        _live_failed_steps(api, descriptor, registration, first)
        failed_steps = _live_failed_steps(api, descriptor, registration, final)
        context = {"repository": REPOSITORY, "base_sha": descriptor["base_sha"],
            "orchestration_id": f"orchestration-{descriptor['cycle_id']}",
            "orchestrator_run_id": request["orchestrator_run_id"],
            "orchestrator_run_attempt": request["orchestrator_attempt"],
            "package_slug": slug, "workflow_path": registration.workflow_path,
            "called_job": registration.called_job, "batch": batch.batch,
            "initial_run_id": first_entry["run_id"], "confirmation_run_id": final_entry["run_id"],
            "confirmation_job_id": final["job_id"], "failed_steps": failed_steps,
            "source_text": read_source(root, descriptor["base_sha"], registration.workflow_path),
            "log_excerpt": "Log unavailable."}
        _require(set(context) == CONTEXT_KEYS, "context differs from the frozen publisher contract")
        try:
            contexts[slug] = _context(context)
        except PublishError as exc:
            raise ContractError("repair context expansion requires manual investigation: unsupported new package context") from exc
    for batch, entry in runs.values():
        _live_run(api, descriptor, batch, entry)
    _current(api, descriptor)
    return [deepcopy(contexts[slug]) for slug in sorted(contexts)]
