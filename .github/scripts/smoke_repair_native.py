"""Exact native validation of a policy-approved, immutable smoke-repair branch.

Policy owns authorization of script changes. This module authenticates its base
contract and frozen candidate metadata, dispatches at most once, and records only
observed Actions evidence. Publishers must call verify(), not trust receipt JSON.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from copy import deepcopy
from datetime import datetime
import hashlib
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from urllib.parse import urlencode

# The parent launches this trusted-base script with Python isolated mode (-I).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from exact_run_aggregation import ContractError as YAMLContractError, _yaml_mapping
from orchestration_contract import (
    ContractError, canonical_json, decode_json, validate_branch,
    validate_current_ref, validate_repository, validate_sha,
)
from smoke_recovery import GitHub

MAX_SECONDS = 60 * 60
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_WORKFLOW_BYTES = 1024 * 1024
MAX_POLLS = 360
MAX_PAGES = 10
RATE_CHECK_REQUESTS = 10
DISPATCH_RATE_RESERVE = 200
VERIFY_RATE_RESERVE = 20
VERIFY_SECONDS = 180
RUNNER = "ubuntu-24.04-arm"
_SLUG = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,98}[A-Za-z0-9])?\Z", re.ASCII)
_JOB = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,99}\Z", re.ASCII)
_WORKFLOW = re.compile(r"\.github/workflows/test-[A-Za-z0-9][A-Za-z0-9_-]{0,99}\.yml\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z", re.ASCII)
_PENDING = {"queued", "in_progress", "pending", "requested", "waiting"}
_STAGE_KEYS = {
    "schema_version", "repository", "repair_id", "base_sha", "branch",
    "candidate_sha", "tree_sha", "workflow_path", "package_slug",
    "proposal_digest", "source_digest",
}
_CONTRACT_KEYS = {
    "called_job", "job_name", "mandatory_steps", "gate_step", "workflow_path", "source_digest",
}
_RECEIPT_KEYS = {"schema_version", "stage", "contract_digest", "status", "run", "job", "steps"}


def _mapping(value, label):
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ContractError(f"{label} must be an object with string keys")
    return value


def _integer(value, label, *, minimum=1, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError(f"{label} must be a bounded integer")
    return value


def _text(value, label):
    if (not isinstance(value, str) or not value or len(value) > 200
            or value != value.strip() or any(ord(char) < 32 for char in value)
            or "${{" in value):
        raise ContractError(f"{label} must be bounded literal text")
    return value


def _match(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ContractError(f"{label} is not canonical")
    return value


def _document(value, label):
    try:
        raw = canonical_json(value).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ContractError(f"{label} is not JSON") from exc
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ContractError(f"{label} exceeds its size limit")
    return _mapping(decode_json(raw), label)


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _same(left, right, label):
    if canonical_json(left) != canonical_json(right):
        raise ContractError(f"{label} does not match authenticated evidence")


def _version(value, keys, label):
    _mapping(value, label)
    if set(value) != keys or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ContractError(f"{label} has an unsupported schema")


def _workflow_path(value):
    path = _match(value, _WORKFLOW, "workflow path")
    if path.rsplit("/", 1)[-1].lower().startswith("test-all-packages"):
        raise ContractError("native validation requires a standalone package workflow")
    return path


def validate_stage(stage):
    """Validate the exact policy/publisher staging schema without performing I/O."""
    _version(stage, _STAGE_KEYS, "stage")
    validate_repository(stage["repository"])
    for field in ("base_sha", "candidate_sha", "tree_sha"):
        validate_sha(stage[field], label=field)
    if stage["candidate_sha"] == stage["base_sha"]:
        raise ContractError("native candidate must differ from base")
    slug = _match(stage["package_slug"], _SLUG, "package slug")
    repair = re.compile(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,9}-" + re.escape(slug) + r"\Z", re.ASCII)
    _match(stage["repair_id"], repair, "repair ID")
    branch = validate_branch(stage["branch"])
    if branch != f"automation/smoke-repair/{stage['repair_id']}":
        raise ContractError("stage must use its unique automation branch")
    _workflow_path(stage["workflow_path"])
    for field in ("proposal_digest", "source_digest"):
        _match(stage[field], _DIGEST, field)
    return _document(stage, "stage")


def derive_native_contract(workflow_yaml, *, repository, base_sha, workflow_path,
                           package_slug, source_digest, called_job=None):
    """Return the six-field policy/native interchange contract.

    workflow_yaml is trusted BASE source; source_digest is the SHA-256 of the
    policy-admitted CANDIDATE source. Optional extra contract metadata is bound
    into the receipt digest, never used to relax native validation.
    """
    _match(source_digest, _DIGEST, "candidate source digest")
    expected = _derive_expectations(
        workflow_yaml, repository=repository, base_sha=base_sha,
        workflow_path=workflow_path, package_slug=package_slug, called_job=called_job,
    )
    return _interchange(expected, source_digest)


def _interchange(expected, source_digest):
    return {
        "called_job": expected["called_job"], "job_name": expected["job_name"],
        "mandatory_steps": [step["name"] for step in expected["required_steps"]],
        "gate_step": expected["final_gate"]["name"],
        "workflow_path": expected["workflow_path"], "source_digest": source_digest,
    }


def _derive_expectations(workflow_yaml, *, repository, base_sha, workflow_path,
                         package_slug, called_job=None):
    """Derive native expectations from trusted base YAML, never model output.

The final gate is the conventional 'Enforce failure status' step when present,
otherwise the shell 'summary' step. Policy must freeze the gate and metadata;
its authorization of edited shell bodies is a separate prerequisite.
"""
    validate_repository(repository)
    validate_sha(base_sha, label="base_sha")
    _workflow_path(workflow_path)
    _match(package_slug, _SLUG, "package slug")
    if not isinstance(workflow_yaml, bytes) or not workflow_yaml or len(workflow_yaml) > MAX_WORKFLOW_BYTES:
        raise ContractError("workflow must be bounded nonempty YAML bytes")
    try:
        workflow = _yaml_mapping(workflow_yaml, "native workflow")
    except YAMLContractError as exc:
        raise ContractError(str(exc)) from exc
    name = _text(workflow.get("name"), "workflow name")
    permissions = {"contents": "read"}
    if workflow.get("permissions") != permissions:
        raise ContractError("native workflow requires contents: read only")
    events = _mapping(workflow.get("on"), "workflow events")
    if "workflow_dispatch" not in events or set(events) - {"workflow_dispatch", "workflow_call"}:
        raise ContractError("native workflow must expose only standalone dispatch and optional workflow_call")
    if events["workflow_dispatch"] not in (None, {}):
        raise ContractError("native dispatch must not require or accept inputs")
    jobs = _mapping(workflow.get("jobs"), "workflow jobs")
    if len(jobs) != 1:
        raise ContractError("native workflow requires exactly one standalone job")
    job_id = _match(next(iter(jobs)), _JOB, "called job")
    if called_job is not None and called_job != job_id:
        raise ContractError("called job does not match trusted workflow")
    job = _mapping(jobs[job_id], "standalone job")
    job_name = _text(job.get("name", job_id), "standalone job name")
    if job.get("runs-on") != RUNNER or job.get("permissions", permissions) != permissions:
        raise ContractError("native job requires the free Arm runner and contents: read only")
    if set(job) & {"uses", "strategy", "needs", "if", "container", "services", "environment"}:
        raise ContractError("native job must be unconditional and standalone")
    if job.get("continue-on-error", False) is not False:
        raise ContractError("native job must propagate failures")
    if "timeout-minutes" in job:
        _integer(job["timeout-minutes"], "job timeout", maximum=60)
    steps = job.get("steps")
    if not isinstance(steps, list) or not 6 <= len(steps) <= 100:
        raise ContractError("native job steps are missing or unbounded")
    names, ids, by_id, descriptors = set(), set(), {}, []
    for index, step in enumerate(steps):
        _mapping(step, "workflow step")
        step_name = _text(step.get("name"), "workflow step name")
        if step_name in names or step_name in {"Set up job", "Complete job"}:
            raise ContractError("workflow step names must be unique and not reserved")
        names.add(step_name)
        identifier = step.get("id")
        if identifier is not None:
            _match(identifier, _JOB, "workflow step ID")
            if identifier in ids:
                raise ContractError("duplicate workflow step ID")
            ids.add(identifier)
            by_id[identifier] = step
        # Actions reserves number 1 for 'Set up job'. Post-action numbers may gap.
        descriptors.append({"id": identifier, "name": step_name, "number": index + 2})
    required_ids = [f"test{number}" for number in range(1, 6)]
    if "test6" in ids:
        required_ids.append("test6")
    elif any(re.match(r"Test\s*6\b", name, re.IGNORECASE) for name in names):
        raise ContractError("a differently identified Test 6 requires an explicit native contract")
    required = [item for item in descriptors if item["id"] in required_ids]
    if [item["id"] for item in required] != required_ids:
        raise ContractError("native workflow must contain Tests 1-5 and optional Test 6 in order")
    for identifier in required_ids:
        step = by_id[identifier]
        if "uses" in step or not isinstance(step.get("run"), str) or not step["run"].strip():
            raise ContractError("mandatory native tests must be explicit shell steps")
    gates = [index for index, step in enumerate(steps) if step["name"] == "Enforce failure status"]
    if not gates:
        gates = [index for index, step in enumerate(steps) if step.get("id") == "summary" and "run" in step]
    if len(gates) != 1:
        raise ContractError("native workflow has no unique immutable final gate")
    gate_index = gates[0]
    gate = steps[gate_index]
    if (gate_index + 2 <= required[-1]["number"] or "uses" in gate
            or not isinstance(gate.get("run"), str) or not gate["run"].strip()
            or gate.get("continue-on-error", False) is not False
            or gate.get("if") not in ("always()", "${{ always() }}")):
        raise ContractError("native final gate must run after all tests and propagate failures")
    frozen = deepcopy(workflow)
    for index, step in enumerate(frozen["jobs"][job_id]["steps"]):
        if index < gate_index and "run" in step:
            step["run"] = None
    final_gate = {**descriptors[gate_index], "sha256": _digest(gate)}
    return {
        "schema_version": 1, "repository": repository, "base_sha": base_sha,
        "workflow_path": workflow_path, "package_slug": package_slug,
        "workflow_name": name, "called_job": job_id, "job_name": job_name,
        "permissions": permissions, "runner_labels": [RUNNER],
        "required_steps": required, "final_gate": final_gate, "workflow_steps": descriptors,
        "metadata_digest": _digest(frozen),
    }


def _when(value, label):
    _match(value, _TIME, label)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} is not a timestamp") from exc


def _state(value, label):
    if "status" not in value or "conclusion" not in value:
        raise ContractError(f"{label} has missing status/conclusion")
    status, conclusion = value.get("status"), value.get("conclusion")
    if status == "completed" and conclusion == "success":
        return True
    if isinstance(status, str) and status in _PENDING and conclusion is None:
        return False
    raise ContractError(f"{label} failed or has malformed status/conclusion")


class NativeValidation:
    def __init__(self, api=None, *, clock=time.monotonic, sleep=time.sleep,
                 deadline=None, timeout_seconds=MAX_SECONDS, poll_interval=90,
                 max_polls=MAX_POLLS, max_pages=MAX_PAGES, wall_clock=time.time):
        """deadline is absolute in clock() units; every budget is capped at 60m."""
        for value, label in ((timeout_seconds, "timeout"), (poll_interval, "poll interval")):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ContractError(f"native {label} must be finite and positive")
        self.clock, self.sleep = clock, sleep
        now = self._clock()
        budget = min(timeout_seconds, MAX_SECONDS)
        if deadline is not None:
            if type(deadline) not in (int, float) or not math.isfinite(deadline):
                raise ContractError("native deadline must be finite")
            budget = min(budget, deadline - now)
        if budget <= 0:
            raise ContractError("native validation deadline expired; not passed")
        self.deadline = now + budget
        self.real_deadline = time.monotonic() + budget
        self.poll_interval = min(poll_interval, MAX_SECONDS)
        self.max_polls = _integer(max_polls, "poll bound", maximum=MAX_POLLS)
        self.max_pages = _integer(max_pages, "pagination bound", maximum=MAX_PAGES)
        self.github = api if api is not None else GitHub(self.real_deadline)
        self._attempted = set()
        self.wall_clock = wall_clock
        self._rate_credit = 0
        self._rate_reserve = DISPATCH_RATE_RESERVE

    def _clock(self):
        value = self.clock()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ContractError("native clock must return a finite number")
        return value

    def remaining(self):
        remaining = min(self.deadline - self._clock(), self.real_deadline - time.monotonic())
        if remaining <= 0:
            raise ContractError("native validation timed out; not passed")
        return remaining

    def _rate_budget(self, minimum_requests=1):
        if self._rate_credit >= minimum_requests:
            return
        for _ in range(4):
            # This endpoint does not consume the primary REST allowance. Never
            # recurse through _api here or assume a shared quota reset occurred.
            try:
                payload = self.github.api("rate_limit", timeout=min(60, self.remaining()))
            except OSError as exc:
                raise ContractError("native API rate evidence unavailable") from exc
            self.remaining()
            resources = _mapping(_mapping(payload, "rate limit").get("resources"), "rate resources")
            core = _mapping(resources.get("core"), "core rate limit")
            limit = _integer(core.get("limit"), "rate limit", maximum=1_000_000)
            available = _integer(core.get("remaining"), "remaining rate limit", minimum=0, maximum=limit)
            reset = _integer(core.get("reset"), "rate reset")
            now = self.wall_clock()
            if type(now) not in (int, float) or not math.isfinite(now) or now <= 0:
                raise ContractError("rate-limit wall clock is invalid")
            if limit < self._rate_reserve + minimum_requests or reset > now + 7200:
                raise ContractError("rate-limit window cannot support bounded validation")
            if available >= self._rate_reserve + minimum_requests:
                self._rate_credit = min(RATE_CHECK_REQUESTS, available - self._rate_reserve)
                return
            delay = reset - now + 1
            if delay <= 0 or delay >= self.remaining():
                raise ContractError("shared API quota cannot recover within validation deadline")
            self.sleep(delay)
            self.remaining()
        raise ContractError("shared API quota remained unavailable after bounded waits")

    def _api(self, endpoint, **kwargs):
        try:
            self._rate_budget()
            self._rate_credit -= 1
            result = self.github.api(endpoint, timeout=min(60, self.remaining()), **kwargs)
        except OSError as exc:
            raise ContractError("native API evidence unavailable") from exc
        self.remaining()
        return result

    def _current(self, stage):
        self._rate_budget(minimum_requests=2)
        for branch, sha in (("main", stage["base_sha"]), (stage["branch"], stage["candidate_sha"])):
            ref = self._api(f"repos/{stage['repository']}/git/ref/heads/{branch}")
            validate_current_ref(ref, expected_sha=sha, branch=branch)

    def _public_repository(self, stage):
        repository = _mapping(self._api(f"repos/{stage['repository']}"), "native repository")
        if repository.get("full_name") != stage["repository"] or repository.get("private") is not False:
            raise ContractError("free hosted native validation requires the exact public repository")

    def _source(self, stage, sha):
        query = urlencode({"ref": sha})
        source = _mapping(self._api(
            f"repos/{stage['repository']}/contents/{stage['workflow_path']}?{query}"
        ), "workflow content")
        if source.get("type") != "file" or source.get("path") != stage["workflow_path"] or source.get("encoding") != "base64":
            raise ContractError("workflow content identity is invalid")
        size = _integer(source.get("size"), "workflow size", maximum=MAX_WORKFLOW_BYTES)
        content = source.get("content")
        if not isinstance(content, str) or len(content) > 2 * MAX_WORKFLOW_BYTES:
            raise ContractError("workflow content is not bounded base64")
        try:
            raw = base64.b64decode(content.replace("\n", ""), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ContractError("workflow content is malformed base64") from exc
        blob_sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        if len(raw) != size or validate_sha(source.get("sha"), label="workflow blob SHA") != blob_sha:
            raise ContractError("workflow content does not match its blob")
        return raw

    def _prepare(self, stage, contract):
        stage = validate_stage(stage)
        contract = _document(contract, "native contract")
        if not _CONTRACT_KEYS <= set(contract):
            raise ContractError("native contract is missing required fields")
        for key in ("workflow_path", "source_digest"):
            if contract[key] != stage[key]:
                raise ContractError(f"native contract {key} differs from stage")
        _match(contract["called_job"], _JOB, "called job")
        self._public_repository(stage)
        self._current(stage)
        commit = _mapping(self._api(
            f"repos/{stage['repository']}/git/commits/{stage['candidate_sha']}"
        ), "candidate commit")
        if commit.get("sha") != stage["candidate_sha"] or _mapping(commit.get("tree"), "candidate tree").get("sha") != stage["tree_sha"]:
            raise ContractError("candidate commit/tree differs from stage")
        parents = commit.get("parents")
        if (not isinstance(parents, list) or len(parents) != 1
                or _mapping(parents[0], "candidate parent").get("sha") != stage["base_sha"]):
            raise ContractError("candidate is not a single commit on the trusted base")
        expected = None
        for sha in (stage["base_sha"], stage["candidate_sha"]):
            self._current(stage)
            raw = self._source(stage, sha)
            if sha == stage["candidate_sha"] and hashlib.sha256(raw).hexdigest() != stage["source_digest"]:
                raise ContractError("candidate workflow source digest differs from stage")
            derived = _derive_expectations(
                raw, repository=stage["repository"],
                base_sha=stage["base_sha"], workflow_path=stage["workflow_path"],
                package_slug=stage["package_slug"], called_job=contract["called_job"],
            )
            _same({key: contract[key] for key in _CONTRACT_KEYS},
                  _interchange(derived, stage["source_digest"]), "native interchange contract")
            if expected is None:
                expected = derived
            else:
                _same(expected, derived, "trusted base/candidate frozen metadata and final gate")
        # Recognized optional expectations cannot contradict the trusted base.
        for key in set(contract) & set(expected):
            _same(contract[key], expected[key], f"native contract {key}")
        expected["contract_digest"] = _digest(contract)
        workflow = _mapping(self._api(
            f"repos/{stage['repository']}/actions/workflows/{stage['workflow_path'].rsplit('/', 1)[-1]}"
        ), "workflow identity")
        workflow_id = _integer(workflow.get("id"), "workflow ID")
        if (workflow.get("path") != stage["workflow_path"] or workflow.get("name") != expected["workflow_name"]
                or workflow.get("state") != "active"):
            raise ContractError("workflow identity does not match trusted base")
        self._current(stage)
        return stage, expected, workflow_id

    def _inventory(self, stage, path, key, query=None):
        items, total = [], None
        for page_number in range(1, self.max_pages + 1):
            self._current(stage)
            parameters = {**(query or {}), "per_page": 100, "page": page_number}
            page = _mapping(self._api(
                f"repos/{stage['repository']}/{path}?{urlencode(parameters)}"
            ), f"{key} page")
            count = _integer(page.get("total_count"), "inventory total_count", minimum=0, maximum=self.max_pages * 100)
            if total is not None and count != total:
                raise ContractError("inventory changed during pagination")
            total = count
            rows = page.get(key)
            if not isinstance(rows, list) or len(rows) != min(100, total - len(items)):
                raise ContractError("inventory pagination is incomplete or malformed")
            for row in rows:
                _mapping(row, "inventory item")
                _integer(row.get("id"), "inventory ID")
            items.extend(rows)
            if len({row["id"] for row in items}) != len(items):
                raise ContractError("inventory contains duplicate IDs")
            self._current(stage)
            if len(items) == total:
                return items
        raise ContractError("inventory pagination bound exhausted")

    def _runs(self, stage):
        workflow_file = stage["workflow_path"].rsplit("/", 1)[-1]
        # Do not filter on event: ANY prior run at this workflow/branch/SHA blocks POST.
        return self._inventory(stage, f"actions/workflows/{workflow_file}/runs", "workflow_runs",
                               {"branch": stage["branch"], "head_sha": stage["candidate_sha"]})

    def _run(self, stage, contract, workflow_id, run_id, payload=None):
        _integer(run_id, "native run ID")
        run = _mapping(payload if payload is not None else self._api(
            f"repos/{stage['repository']}/actions/runs/{run_id}"
        ), "native run")
        for key, expected in (("id", run_id), ("workflow_id", workflow_id), ("run_attempt", 1)):
            if _integer(run.get(key), key) != expected:
                raise ContractError(f"native run {key} mismatch")
        for key in ("repository", "head_repository"):
            if _mapping(run.get(key), key).get("full_name") != stage["repository"]:
                raise ContractError(f"native run {key} mismatch")
        expected = {"head_sha": stage["candidate_sha"], "head_branch": stage["branch"],
                    "path": stage["workflow_path"], "event": "workflow_dispatch", "name": contract["workflow_name"]}
        for key, value in expected.items():
            if run.get(key) != value:
                raise ContractError(f"native run {key} mismatch")
        if _mapping(run.get("head_commit"), "head commit").get("id") != stage["candidate_sha"]:
            raise ContractError("native run head commit mismatch")
        for key, url in (("url", f"https://api.github.com/repos/{stage['repository']}/actions/runs/{run_id}"),
                         ("html_url", f"https://github.com/{stage['repository']}/actions/runs/{run_id}")):
            if run.get(key) != url:
                raise ContractError(f"native run {key} mismatch")
        completed = _state(run, "native run")
        created, updated = _when(run.get("created_at"), "run created_at"), _when(run.get("updated_at"), "run updated_at")
        if created > updated:
            raise ContractError("native run timestamps are reversed")
        if completed or run.get("run_started_at") is not None:
            started = _when(run.get("run_started_at"), "run started_at")
            if not created <= started <= updated:
                raise ContractError("native run start is outside its window")
        if completed and (updated - created).total_seconds() > MAX_SECONDS:
            raise ContractError("native run exceeded the 60-minute limit")
        return run

    def _unique_run(self, stage, contract, workflow_id, expected_id=None):
        runs = self._runs(stage)
        if len(runs) > 1:
            raise ContractError("native dispatch has multiple runs; exact registration is ambiguous")
        if not runs:
            return None
        run_id = runs[0]["id"]
        if expected_id is not None and run_id != expected_id:
            raise ContractError("dispatch response/receipt run ID differs from exact registration")
        self._run(stage, contract, workflow_id, run_id, runs[0])
        return run_id

    def _job(self, stage, contract, run, job):
        _mapping(job, "native job")
        job_id = _integer(job.get("id"), "native job ID")
        for key, value in (("run_id", run["id"]), ("run_attempt", 1)):
            if _integer(job.get(key), key) != value:
                raise ContractError(f"native job {key} mismatch")
        for key, value in (("head_sha", stage["candidate_sha"]), ("head_branch", stage["branch"]),
                           ("name", contract["job_name"]), ("workflow_name", contract["workflow_name"]),
                           ("run_url", run["url"]),
                           ("url", f"https://api.github.com/repos/{stage['repository']}/actions/jobs/{job_id}"),
                           ("html_url", f"https://github.com/{stage['repository']}/actions/runs/{run['id']}/job/{job_id}")):
            if job.get(key) != value:
                raise ContractError(f"native job {key} mismatch")
        if job.get("labels") != contract["runner_labels"]:
            raise ContractError("native job runner labels mismatch")
        if not _state(job, "native job"):
            return None
        _integer(job.get("runner_id"), "native runner ID")
        _text(job.get("runner_name"), "native runner name")
        # Labels describe runs-on, not the runner that actually executed the job.
        if (_integer(job.get("runner_group_id"), "native runner group ID", minimum=0) != 0
                or job.get("runner_group_name") != "GitHub Actions"):
            raise ContractError("native job did not execute on the standard GitHub-hosted runner group")
        started, ended = _when(job.get("started_at"), "job started_at"), _when(job.get("completed_at"), "job completed_at")
        if not _when(run["run_started_at"], "run started_at") <= started <= ended <= _when(run["updated_at"], "run updated_at"):
            raise ContractError("native job timestamps are outside run window")
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps or len(steps) > 200:
            raise ContractError("native step inventory is missing or unbounded")
        observed, names, last_number, previous_end = [], set(), 0, started
        for step in steps:
            _mapping(step, "native step")
            name = _text(step.get("name"), "native step name")
            number = _integer(step.get("number"), "native step number", maximum=1000)
            if name in names or number <= last_number:
                raise ContractError("native step names/numbers are duplicated or out of order")
            if step.get("status") != "completed" or step.get("conclusion") != "success":
                raise ContractError("native step did not complete successfully")
            begin, end = _when(step.get("started_at"), "step started_at"), _when(step.get("completed_at"), "step completed_at")
            if not previous_end <= begin <= end <= ended:
                raise ContractError("native step timestamps are outside job window or out of order")
            names.add(name)
            last_number, previous_end = number, end
            observed.append({key: step[key] for key in ("name", "number", "status", "conclusion", "started_at", "completed_at")})
        by_name = {item["name"]: item for item in observed}
        for expected in [*contract["required_steps"], contract["final_gate"]]:
            step = by_name.get(expected["name"])
            if step is None or step["number"] != expected["number"]:
                raise ContractError("mandatory test/final gate is missing or has the wrong number")
        for expected in contract["workflow_steps"]:
            step = by_name.get(expected["name"])
            if step is None or step["number"] != expected["number"]:
                raise ContractError("native workflow step inventory is incomplete or mismatched")
        return {key: job[key] for key in (
            "id", "run_id", "run_attempt", "name", "head_sha", "head_branch", "workflow_name",
            "status", "conclusion", "started_at", "completed_at", "labels", "runner_id", "runner_name",
            "runner_group_id", "runner_group_name", "html_url",
        )}, observed

    def _collect(self, stage, contract, workflow_id, run_id, *, allow_pending=False):
        run = self._run(stage, contract, workflow_id, run_id)
        if run["status"] != "completed":
            if allow_pending:
                return None
            raise ContractError("native run is not completed; not passed")
        jobs = self._inventory(stage, f"actions/runs/{run_id}/attempts/1/jobs", "jobs")
        if not jobs and allow_pending:
            return None
        if len(jobs) != 1:
            raise ContractError("native attempt must contain exactly one standalone job")
        observation = self._job(stage, contract, run, jobs[0])
        if observation is None:
            if allow_pending:
                return None
            raise ContractError("native job is not completed; not passed")
        job, steps = observation
        individual = self._mapping_job(stage, contract, run, job["id"])
        _same(observation, individual, "individual job versus complete attempt inventory")
        latest = self._run(stage, contract, workflow_id, run_id)
        _same(run, latest, "completed native run snapshot")
        if self._unique_run(stage, contract, workflow_id, run_id) != run_id:
            raise ContractError("native run has no unique exact evidence")
        self._public_repository(stage)
        self._current(stage)
        run_observation = {key: run[key] for key in (
            "id", "workflow_id", "run_attempt", "name", "path", "head_sha", "head_branch", "event",
            "status", "conclusion", "created_at", "run_started_at", "updated_at", "html_url",
        )}
        run_observation.update(repository=stage["repository"], head_repository=stage["repository"])
        self.remaining()
        return {"schema_version": 1, "stage": deepcopy(stage), "contract_digest": contract["contract_digest"],
                "status": "passed", "run": run_observation, "job": job, "steps": steps}

    def _mapping_job(self, stage, contract, run, job_id):
        payload = self._api(f"repos/{stage['repository']}/actions/jobs/{job_id}")
        if _mapping(payload, "individual job").get("id") != job_id:
            raise ContractError("individual native job ID mismatch")
        return self._job(stage, contract, run, payload)

    @staticmethod
    def _dispatch_id(response, stage):
        if response is None:
            return None
        _mapping(response, "dispatch response")
        if "workflow_run_id" not in response or set(response) - {"workflow_run_id", "run_url", "html_url"}:
            raise ContractError("dispatch response is malformed")
        run_id = _integer(response["workflow_run_id"], "dispatch run ID")
        for key, expected in (("run_url", f"https://api.github.com/repos/{stage['repository']}/actions/runs/{run_id}"),
                              ("html_url", f"https://github.com/{stage['repository']}/actions/runs/{run_id}")):
            if key in response and response[key] != expected:
                raise ContractError("dispatch response URL does not match its run identity")
        return run_id

    def dispatch_and_wait(self, stage, contract):
        """POST ref-only once, reconcile exact registration, and return observed evidence.

        A timeout or ambiguity raises ContractError and never authorizes publication.
        No cancellation, re-run, branch mutation, or PR API is used here.
        """
        stage, contract, workflow_id = self._prepare(stage, contract)
        identity = (stage["repository"], stage["branch"], stage["candidate_sha"], stage["workflow_path"])
        if identity in self._attempted:
            raise ContractError("this native dispatch was already attempted; never redispatch")
        # Reserve the empty inventory (five reads), repository, refs, and POST.
        # A reset wait must not make the no-prior-run observation stale.
        self._rate_budget(minimum_requests=9)
        if self._runs(stage):
            raise ContractError("prior native runs exist for this workflow/branch/SHA; refusing duplicate dispatch")
        self._public_repository(stage)
        self._current(stage)
        self._attempted.add(identity)
        workflow_file = stage["workflow_path"].rsplit("/", 1)[-1]
        try:
            response = self._api(f"repos/{stage['repository']}/actions/workflows/{workflow_file}/dispatches",
                                 payload={"ref": stage["branch"]})
        except ContractError:
            # POST may have succeeded. Reconcile this unique branch, never POST again.
            response = None
        run_id = self._dispatch_id(response, stage)
        for attempt in range(self.max_polls):
            # The complete run inventory brackets every poll with both ref checks.
            exact_id = self._unique_run(stage, contract, workflow_id, run_id)
            if exact_id is not None:
                run_id = exact_id
                receipt = self._collect(stage, contract, workflow_id, run_id, allow_pending=True)
                if receipt is not None:
                    return receipt
            elif run_id is not None:
                self._run(stage, contract, workflow_id, run_id)
            if attempt + 1 < self.max_polls:
                self.sleep(min(self.poll_interval, self.remaining()))
                self.remaining()
        raise ContractError("native polling bound exhausted without exact completed evidence; not passed")

    def verify(self, stage, receipt, contract):
        """Read-only publisher gate: reauthenticate every receipt binding and observation."""
        self._rate_reserve = VERIFY_RATE_RESERVE
        stage = validate_stage(stage)
        receipt = _document(receipt, "native receipt")
        _version(receipt, _RECEIPT_KEYS, "native receipt")
        if receipt["status"] != "passed":
            raise ContractError("native receipt does not report a pass")
        _same(receipt["stage"], stage, "receipt stage")
        _same(receipt["contract_digest"], _digest(_document(contract, "native contract")), "receipt contract digest")
        run_id = _integer(_mapping(receipt["run"], "receipt run").get("id"), "receipt run ID")
        stage, contract, workflow_id = self._prepare(stage, contract)
        if self._unique_run(stage, contract, workflow_id, run_id) != run_id:
            raise ContractError("native receipt has no unique exact registration")
        observed = self._collect(stage, contract, workflow_id, run_id)
        _same(receipt, observed, "native receipt")
        self.remaining()
        return observed


def verify_native_receipt(stage, receipt, contract, *, api=None, **options):
    """Convenience publisher entry point with the same injected API/clock options."""
    return NativeValidation(api, **{"timeout_seconds": VERIFY_SECONDS, **options}).verify(stage, receipt, contract)


def _load(path):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_DOCUMENT_BYTES:
            raise ContractError("native input must be a bounded regular file without hard links")
        raw = source.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ContractError("native input exceeds its size limit")
    return decode_json(raw)


def _write(path, value):
    raw = (canonical_json(value) + "\n").encode("utf-8")
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ContractError("native output exceeds its size limit")
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags, 0o600), "wb") as output:
        info = os.fstat(output.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ContractError("native output must be a regular file without hard links")
        output.truncate(0)
        output.write(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dispatch", "verify"), required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", help="verify input; defaults to --output")
    args = parser.parse_args(argv)
    output = Path(args.output)
    try:
        if output.resolve() in {Path(args.stage).resolve(), Path(args.contract).resolve()}:
            raise ContractError("native output must not overwrite stage or contract input")
        stage, contract = _load(args.stage), _load(args.contract)
        if args.mode == "dispatch" and args.receipt:
            raise ContractError("--receipt is only valid in verify mode")
        receipt = _load(args.receipt or args.output) if args.mode == "verify" else None
        _write(output, {"schema_version": 1, "status": "not_passed"})
        validator = NativeValidation(timeout_seconds=MAX_SECONDS if args.mode == "dispatch" else VERIFY_SECONDS)
        result = (validator.dispatch_and_wait(stage, contract) if args.mode == "dispatch"
                  else validator.verify(stage, receipt, contract))
        _write(output, result)
    except (ContractError, OSError) as exc:
        print(f"Native validation not passed: {exc}", file=sys.stderr)
        if output.resolve() not in {Path(args.stage).resolve(), Path(args.contract).resolve()}:
            try:
                _write(output, {"schema_version": 1, "status": "not_passed"})
            except (ContractError, OSError):
                pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
