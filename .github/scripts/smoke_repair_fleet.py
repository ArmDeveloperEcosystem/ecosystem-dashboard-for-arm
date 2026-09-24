"""Run an immutable repair candidate's full fleet without publishing site data.

Only trusted-main code executes in this controller. Bundle admission is a live
publisher callback, not an assertion supplied by a candidate or model. A receipt
is evidence to re-verify, never authorization to publish or merge.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))

import exact_run_aggregation as exact
import batch_artifact_attestation as batch_attestation
import orchestration_contract as orchestration
from orchestration_contract import ContractError
from smoke_recovery import GitHub
from smoke_repair_evidence import read_json, write_json
from smoke_repair_session import VerificationSession, _Reader, session_for
from package_result_policy import validate_publishable_result

REPOSITORY = "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm"
MAX_SECONDS = 5 * 60 * 60
VERIFY_SECONDS = 30 * 60
MAX_REQUESTS = 12_000
MAX_PAGES = 10
MAX_POLLS = 600
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
DESCRIPTOR_KEYS = {"schema_version", "repository", "base_sha", "candidate_sha", "branch", "cycle_id", "iteration"}
RECEIPT_KEYS = {"schema_version", "kind", "descriptor", "status", "publishing", "topology_sha256",
                "started_at", "completed_at", "history", "manifest", "attestation", "summary"}
PENDING = {"queued", "in_progress", "pending", "requested", "waiting"}


def _integer(value, label, minimum=1, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError(f"invalid {label}")
    return value


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ContractError(f"invalid {label}")
    return value


def _same(actual, expected, label):
    if orchestration.canonical_json(actual) != orchestration.canonical_json(expected):
        raise ContractError(f"{label} differs from live evidence")


def validate_descriptor(value):
    value = _mapping(value, "fleet descriptor")
    if set(value) != DESCRIPTOR_KEYS or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ContractError("unsupported fleet descriptor")
    if value["repository"] != REPOSITORY:
        raise ContractError("fleet is restricted to the public dashboard repository")
    for field in ("base_sha", "candidate_sha"):
        orchestration.validate_sha(value[field])
    if value["base_sha"] == value["candidate_sha"]:
        raise ContractError("fleet candidate must differ from base")
    branch = orchestration.validate_branch(value["branch"])
    if not isinstance(value["cycle_id"], str) or not re.fullmatch(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,9}", value["cycle_id"]):
        raise ContractError("invalid repair cycle identity")
    _integer(value["iteration"], "cycle iteration", maximum=3)
    if branch != f"automation/smoke-repair-cycle/{value['cycle_id']}/iteration-{value['iteration']}":
        raise ContractError("fleet branch must bind exact cycle and iteration")
    return deepcopy(value)


def _time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ContractError("invalid fleet timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("invalid fleet timestamp") from exc


def validate_local_receipt(descriptor, receipt, *, repository_root):
    """Check local receipt consistency, not live artifact authenticity.

    Reserved for packaging the current trusted native job's own output. A
    downstream consumer must still call FleetValidation.verify independently.
    """
    from smoke_repair_cycle_context import _receipt_failures
    descriptor = validate_descriptor(descriptor)
    exact.validate_checkout_binding(repository_root, descriptor["base_sha"])
    topology = exact.discover_topology(repository_root)
    _receipt_failures(receipt, descriptor, topology)
    _same(receipt["topology_sha256"], exact.topology_sha256(topology), "local topology")
    selected = [entries[-1] for entries in receipt["history"]]
    expected_manifest = {"schema": exact.MANIFEST_SCHEMA, "version": exact.MANIFEST_VERSION,
        "repository": REPOSITORY, "branch": descriptor["branch"], "head_sha": descriptor["candidate_sha"],
        "topology_sha256": receipt["topology_sha256"], "orchestration_id": f"orchestration-{descriptor['cycle_id']}",
        "created_at": receipt["completed_at"], "batches": [entry["record"] for entry in selected]}
    manifest = exact.validate_manifest(expected_manifest, topology=topology, expected_repository=REPOSITORY,
        expected_branch=descriptor["branch"], expected_sha=descriptor["candidate_sha"],
        expected_orchestration_id=expected_manifest["orchestration_id"],
        expected_dispatch_nonces=[entry["dispatch_nonce"] for entry in selected],
        expected_not_before=receipt["started_at"], expected_not_after=receipt["completed_at"])
    _same(receipt["manifest"], manifest, "local manifest")
    attestation = _mapping(receipt["attestation"], "local attestation")
    proofs = attestation.get("batches")
    if type(proofs) is not list or len(proofs) != len(topology):
        raise ContractError("local artifact proof inventory is incomplete")
    expected_proofs = []
    for batch, entry, proof in zip(topology, selected, proofs, strict=True):
        proof = _mapping(proof, "local batch proof")
        digest = proof.get("attestation_sha256")
        packages = proof.get("packages")
        if (type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or type(packages) is not list or len(packages) != len(batch.packages)):
            raise ContractError("local artifact proof is malformed")
        expected_packages = []
        for registration, observation, package in zip(batch.packages, entry["observations"], packages, strict=True):
            package = _mapping(package, "local package proof")
            digest = package.get("sha256")
            if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ContractError("local package proof digest is malformed")
            expected_packages.append({"package_slug": registration.package_slug,
                "workflow_path": registration.workflow_path, "job_id": observation["job_id"],
                "run_status": observation["status"], "sha256": digest})
        expected_proofs.append({"batch": batch.batch, "run_id": entry["run_id"], "run_attempt": 1,
            "artifact_id": entry["record"]["artifact"]["id"],
            "artifact_digest": entry["record"]["artifact"]["digest"],
            "attestation_sha256": proof["attestation_sha256"], "packages": expected_packages})
    _same(attestation, {"schema_version": 1, "kind": "candidate-fleet-artifact-attestation",
        "descriptor": descriptor, "manifest_sha256": hashlib.sha256(
            (exact.canonical_json(manifest) + "\n").encode("ascii")).hexdigest(),
        "batches": expected_proofs, "overall_status": receipt["status"]}, "local attestation")
    return receipt


def _required_steps(raw, registration):
    """Support both explicit test IDs and the reviewed composite-action wrappers."""
    workflow = exact._yaml_mapping(raw, "trusted fleet workflow")
    jobs = _mapping(workflow.get("jobs"), "trusted package jobs")
    if list(jobs) != [registration.called_job]:
        raise ContractError("package job differs from registered topology")
    job = _mapping(jobs[registration.called_job], "trusted package job")
    if job.get("runs-on") != "ubuntu-24.04-arm" or job.get("continue-on-error", False) is not False:
        raise ContractError("package must propagate failures on hosted Arm")
    if any(key in job for key in ("if", "strategy", "uses", "environment")):
        raise ContractError("package job cannot be conditional, privileged or expanded")
    steps = job.get("steps")
    if not isinstance(steps, list) or not 6 <= len(steps) <= 100:
        raise ContractError("trusted package steps are missing or unbounded")
    probes, gates = {}, []
    names, ids = set(), set()
    for index, step in enumerate(steps):
        _mapping(step, "trusted step")
        name, identifier = step.get("name"), step.get("id")
        for value, seen in ((name, names), (identifier, ids)):
            if value is not None:
                if not isinstance(value, str) or not value or value in seen:
                    raise ContractError("duplicate or malformed trusted step identity")
                seen.add(value)
        match = re.fullmatch(r"test([1-6])", identifier or "")
        if match is None:
            match = re.match(r"Test\s+([1-6])\s*(?:[-:]|$)", name or "", re.I)
        if match:
            number = int(match[1])
            if number in probes or not isinstance(name, str):
                raise ContractError("required probe is duplicate or unnamed")
            probes[number] = {"number": index + 2, "name": name, "probe": number}
        if name == "Enforce failure status":
            gates.append(index)
    if set(probes) not in (set(range(1, 6)), set(range(1, 7))):
        raise ContractError("trusted package does not expose all five required probes")
    if [probes[n]["number"] for n in sorted(probes)] != sorted(p["number"] for p in probes.values()):
        raise ContractError("required probes are out of order")
    if not gates:
        gates = [i for i, s in enumerate(steps) if isinstance(s.get("run"), str)
                 and s.get("if") in ("always()", "${{ always() }}")
                 and (s.get("id") == "summary" or "steps.summary.outputs.should_fail" in s["run"])]
        if len(gates) > 1:
            gates = [gates[-1]]
    if len(gates) != 1:
        raise ContractError("trusted package has no unambiguous final failure gate")
    gate_index = gates[0]
    gate = steps[gate_index]
    if (gate_index + 2 <= max(p["number"] for p in probes.values())
            or gate.get("continue-on-error", False) is not False
            or gate.get("if") not in ("always()", "${{ always() }}")
            or not isinstance(gate.get("run"), str) or not gate["run"].strip()):
        raise ContractError("trusted failure gate is not unconditional after all probes")
    # Test 6 is optional only when the reviewed base explicitly declares it so.
    regression_policy = job.get("outputs", {}).get("regression_policy")
    required = [probes[n] for n in range(1, 6)]
    if 6 in probes and regression_policy not in {"not_applicable", "not-applicable"}:
        required.append(probes[6])
    return {"required": required, "gate": {"number": gate_index + 2, "name": gate.get("name")}}


def _failed_result(payload, *, registration, batch, run, job):
    """Authenticate negative-only results even when installation found no version.

    The publishing validator deliberately rejects placeholder versions. A real
    failed install may produce one; that is useful failure feedback, never green
    evidence or a reason to manufacture a version.
    """
    result = exact._mapping(payload, "failed package result")
    exact._exact_keys(result, exact._RESULT_KEYS, "failed package result")
    if result.get("schema_version") != "2.0" or job["conclusion"] != "failure":
        raise ContractError("negative package result requires an exact failed job")
    for key, keys in (("package", exact._PACKAGE_KEYS), ("run", exact._RESULT_RUN_KEYS),
                      ("tests", exact._TEST_KEYS), ("metadata", exact._METADATA_KEYS)):
        exact._exact_keys(exact._mapping(result.get(key), key), keys, key)
    observed_run, metadata = result["run"], result["metadata"]
    for field in ("name", "version"):
        exact._bounded_text(result["package"][field], field, 200)
    for field, expected in {"id": str(run["id"]), "attempt": "1", "url": job["html_url"],
        "job_name": job["name"], "status": "failure", "runner": {"os": "ubuntu-24.04", "arch": "arm64"}}.items():
        if observed_run.get(field) != expected:
            raise ContractError("failed package result has a different run or job identity")
    if not _time(job["started_at"]) <= _time(observed_run.get("timestamp")) <= _time(job["completed_at"]):
        raise ContractError("failed package result lies outside exact job window")
    for field, expected in {"package_slug": registration.package_slug, "batch_title": f"Batch {batch}",
        "contract_version": "2.0", "job_url_resolution_status": "central_exact", "badge_status": "failing",
        "dashboard_link": f"/linux/opensource_packages/{registration.package_slug}"}.items():
        if metadata.get(field) != expected:
            raise ContractError("failed package result registration is inconsistent")
    details = exact._validate_test_details(result["tests"]["details"])
    for detail in details:
        match = exact._RUN_URL_RE.fullmatch(detail["url"])
        if (match is None or match.group("repository") != REPOSITORY
                or int(match.group("run_id")) != run["id"] or int(match.group("job_id")) != job["id"]):
            raise ContractError("failed probe detail references another native job")
    if validate_publishable_result(result) != "failure":
        raise ContractError("failed package counters do not establish a real failure")
    return deepcopy(result)


class FleetValidation:
    @classmethod
    def verifier(cls, api, *, now):
        """Nested read verification shares its caller's remaining hard budget."""
        upstream = api
        for _ in range(16):
            if type(upstream) is not _Reader:
                break
            upstream = upstream.delegate
        else:
            raise ContractError("verification reader nesting exceeds budget")
        if type(upstream) is cls:
            return cls(api=api, clock=upstream.clock, sleep=upstream.sleep,
                wall_clock=upstream.wall_clock, timeout_seconds=upstream.remaining())
        return cls(api=api, wall_clock=lambda: now, timeout_seconds=VERIFY_SECONDS)

    def __init__(self, api=None, *, clock=time.monotonic, sleep=time.sleep, wall_clock=time.time,
                 timeout_seconds=MAX_SECONDS, poll_interval=300, max_polls=MAX_POLLS,
                 max_requests=MAX_REQUESTS, nonce_factory=orchestration.generate_dispatch_nonce,
                 session=None):
        for value in (timeout_seconds, poll_interval):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ContractError("fleet time budgets must be finite and positive")
        self.clock, self.sleep, self.wall_clock = clock, sleep, wall_clock
        self.deadline = clock() + min(timeout_seconds, MAX_SECONDS)
        self.real_deadline = time.monotonic() + min(timeout_seconds, MAX_SECONDS)
        self.github = api or GitHub(self.real_deadline)
        self.session = session_for(api, session)
        self.poll_interval = min(poll_interval, 300)
        self.max_polls = _integer(max_polls, "poll budget", maximum=MAX_POLLS)
        self.max_requests = _integer(max_requests, "API budget", maximum=MAX_REQUESTS)
        self.nonce_factory = nonce_factory
        self.requests = 0
        self.credit = 0
        self.attempted = set()

    def remaining(self):
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ContractError("invalid fleet clock")
        remaining = min(self.deadline - now, self.real_deadline - time.monotonic())
        if remaining <= 0:
            raise ContractError("fleet deadline expired; not passed")
        return remaining

    def now(self):
        value = self.wall_clock()
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ContractError("invalid fleet wall clock")
        return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def api(self, endpoint, **options):
        self.remaining()
        timeout = options.pop("timeout", 60)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ContractError("fleet API timeout must be finite and positive")
        if self.requests >= self.max_requests:
            raise ContractError("fleet API request budget exhausted")
        if not self.credit:
            for retry in range(2):
                quota = self.github.api("rate_limit", timeout=min(60, self.remaining()))
                self.remaining()
                core = _mapping(_mapping(quota, "rate limit").get("resources"), "rate resources").get("core")
                core = _mapping(core, "core quota")
                limit = _integer(core.get("limit"), "rate limit", maximum=1_000_000)
                available = _integer(core.get("remaining"), "rate remaining", minimum=0, maximum=limit)
                if available > 220:
                    self.credit = min(20, available - 220)
                    break
                reset = core.get("reset")
                delay = reset - self.wall_clock() + 1 if type(reset) is int else 0
                if retry or not 0 < delay < min(3602, self.remaining()):
                    raise ContractError("fleet rate reserve is unavailable; not passed")
                self.sleep(delay)
                if self.session is not None:
                    self.session.after_wait()
        self.credit -= 1
        self.requests += 1
        try:
            result = self.github.api(endpoint, timeout=min(60, timeout, self.remaining()), **options)
        except OSError as exc:
            raise ContractError("fleet API evidence unavailable") from exc
        self.remaining()
        return result

    def _current(self, descriptor):
        for branch, sha in (("main", descriptor["base_sha"]), (descriptor["branch"], descriptor["candidate_sha"])):
            orchestration.validate_current_ref(self.api(
                f"repos/{REPOSITORY}/git/ref/heads/{branch}"), expected_sha=sha, branch=branch)

    def _attest(self, descriptor, bundle_receipt, repository_root, attest_candidate):
        if not callable(attest_candidate):
            raise ContractError("live bundle attestor is required")
        self._current(descriptor)
        observed = attest_candidate(deepcopy(descriptor), deepcopy(bundle_receipt), api=self,
                                    repository_root=repository_root)
        _same(validate_descriptor(observed), descriptor, "live bundle attestation")
        self.remaining()
        self._current(descriptor)

    def _prepare(self, descriptor, repository_root, bundle_receipt, attest_candidate):
        descriptor = validate_descriptor(descriptor)
        repository_root = Path(repository_root)
        exact.validate_checkout_binding(repository_root, descriptor["base_sha"])
        self._attest(descriptor, bundle_receipt, repository_root, attest_candidate)
        repo = self.api(f"repos/{REPOSITORY}")
        if not isinstance(repo, dict) or repo.get("full_name") != REPOSITORY or repo.get("private") is not False:
            raise ContractError("fleet requires the exact public repository")
        topology = exact.discover_topology(repository_root)
        if len(topology) > orchestration.BATCH_COUNT:
            raise ContractError("fleet topology exceeds the reviewed orchestration dispatch contract")
        if exact.topology_payload(topology)["mutable_external_actions"]:
            raise ContractError("fleet topology has mutable execution dependencies")
        self.contracts = {}
        self.summary_contracts = {}
        self.repository_root = repository_root
        self.workflow_ids = {}
        for batch in topology:
            self.remaining()
            workflow = exact._yaml_mapping((repository_root / batch.workflow_path).read_bytes(), "trusted batch")
            self.summary_contracts[batch.batch] = [{"number": index + 2, "name": step.get("name")}
                for index, step in enumerate(workflow["jobs"]["summary"]["steps"])
                if step.get("id") in {"collect", "attest"}
                or str(step.get("uses", "")).startswith("actions/upload-artifact@")]
            if len(self.summary_contracts[batch.batch]) != 3:
                raise ContractError("fleet requires reviewed collector, attester and uploader")
            metadata = self.api(f"repos/{REPOSITORY}/actions/workflows/{Path(batch.workflow_path).name}")
            if not isinstance(metadata, dict) or any(metadata.get(k) != v for k, v in {
                "path": batch.workflow_path, "name": batch.workflow_name, "state": "active",
            }.items()):
                raise ContractError("registered batch workflow is not active or differs from trusted base")
            self.workflow_ids[batch.batch] = _integer(metadata.get("id"), "batch workflow ID")
            for package in batch.packages:
                raw = exact._read_regular_file(repository_root / package.workflow_path, root=repository_root,
                    label="trusted package", maximum_bytes=exact.MAX_WORKFLOW_FILE_BYTES)
                self.contracts[package.package_slug] = _required_steps(raw, package)
        self._current(descriptor)
        return descriptor, topology

    def _inventory(self, path, key, query=None):
        rows, total = [], None
        for number in range(1, MAX_PAGES + 1):
            params = {**(query or {}), "per_page": 100, "page": number}
            page = _mapping(self.api(f"repos/{REPOSITORY}/{path}?{urlencode(params)}"), "inventory page")
            count = _integer(page.get("total_count"), "inventory count", minimum=0, maximum=MAX_PAGES * 100)
            if total is not None and count != total:
                raise ContractError("fleet inventory changed during pagination")
            total = count
            items = page.get(key)
            if not isinstance(items, list) or len(items) != min(100, total - len(rows)):
                raise ContractError("fleet inventory is incomplete")
            for item in items:
                _integer(_mapping(item, "inventory item").get("id"), "inventory ID")
            rows.extend(items)
            if len({item["id"] for item in rows}) != len(rows):
                raise ContractError("fleet inventory has duplicate IDs")
            if len(rows) == total:
                return rows
        raise ContractError("fleet inventory exceeds pagination bound")

    def _runs(self, descriptor, batch):
        return self._inventory(f"actions/workflows/{Path(batch.workflow_path).name}/runs", "workflow_runs",
            {"branch": descriptor["branch"], "head_sha": descriptor["candidate_sha"]})

    @staticmethod
    def _orchestration_id(descriptor):
        return f"orchestration-{descriptor['cycle_id']}"

    def _validate_run(self, descriptor, batch, nonce, payload, expected_id=None):
        run = _mapping(payload, "fleet run")
        orchestration.validate_run(run, batch=batch.batch, orchestration_id=self._orchestration_id(descriptor),
            dispatch_nonce=nonce, expected_sha=descriptor["candidate_sha"], branch=descriptor["branch"],
            repository=REPOSITORY, expected_run_id=expected_id, require_completed=False)
        if (run.get("workflow_id") != self.workflow_ids[batch.batch]
                or _mapping(run.get("head_repository"), "head repository").get("full_name") != REPOSITORY
                or _mapping(run.get("head_commit"), "head commit").get("id") != descriptor["candidate_sha"]):
            raise ContractError("fleet run workflow/repository/commit identity mismatch")
        for key, expected in {
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run['id']}",
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}",
        }.items():
            if run.get(key) != expected:
                raise ContractError("fleet run URL identity mismatch")
        if not self.started <= _time(run.get("created_at")) <= _time(run.get("updated_at")) <= _time(self.now()):
            raise ContractError("fleet run is outside the current validation window")
        return run

    def _select(self, descriptor, batch, nonce, expected_id=None):
        title = orchestration.expected_run_name(batch.batch, self._orchestration_id(descriptor), nonce)
        matches = [r for r in self._runs(descriptor, batch) if r.get("display_title") == title]
        if not matches:
            return None
        if len(matches) != 1:
            raise ContractError("fleet registration is ambiguous")
        self._validate_run(descriptor, batch, nonce, matches[0], expected_id)
        return self._validate_run(descriptor, batch, nonce,
            self.api(f"repos/{REPOSITORY}/actions/runs/{matches[0]['id']}"), matches[0]["id"])

    def _dispatch(self, descriptor, batch, history):
        key = (descriptor["candidate_sha"], batch.batch, len(history))
        if key in self.attempted or len(history) > 1:
            raise ContractError("candidate batch retry budget exhausted")
        # Full bundle re-admission occurs at preparation and final receipt only.
        # Immutable Git objects cannot change while these exact refs stay fixed.
        self._current(descriptor)
        existing = self._runs(descriptor, batch)
        if {r["id"] for r in existing} != {r["run_id"] for r in history}:
            raise ContractError("candidate batch has an unclaimed prior run")
        for entry in history:
            observed = self._select(descriptor, batch, entry["dispatch_nonce"], entry["run_id"])
            if observed is None or observed.get("conclusion") != "failure" or observed.get("status") != "completed":
                raise ContractError("confirmation requires the exact completed failed first dispatch")
        nonce = orchestration.validate_dispatch_nonce(self.nonce_factory())
        if nonce in self.nonces:
            raise ContractError("dispatch nonce reused")
        self.nonces.add(nonce)
        self.attempted.add(key)  # An ambiguous write is never retried.
        self._current(descriptor)
        self.api(f"repos/{REPOSITORY}/actions/workflows/{Path(batch.workflow_path).name}/dispatches",
            payload=orchestration.batch_dispatch_payload(batch=batch.batch,
                orchestration_id=self._orchestration_id(descriptor), dispatch_nonce=nonce,
                expected_sha=descriptor["candidate_sha"], branch=descriptor["branch"]))
        self._current(descriptor)
        return nonce

    def _job_observation(self, descriptor, batch, package, run, job):
        normalized = exact.validate_job_api(job, registration=package, repository=REPOSITORY, run=run)
        expected = {"head_sha": descriptor["candidate_sha"], "head_branch": descriptor["branch"],
                    "labels": ["ubuntu-24.04-arm"], "runner_group_id": 0, "runner_group_name": "GitHub Actions",
                    "run_url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run['id']}",
                    "url": f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{job['id']}"}
        if any(job.get(key) != value for key, value in expected.items()):
            raise ContractError("fleet package job did not run on the exact hosted Arm candidate")
        _integer(job.get("runner_group_id"), "hosted runner group", minimum=0, maximum=0)
        _integer(job.get("runner_id"), "hosted runner ID")
        if not isinstance(job.get("runner_name"), str) or not job["runner_name"]:
            raise ContractError("hosted runner identity missing")
        steps = job.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 200:
            raise ContractError("fleet job has no bounded step inventory")
        by_number, seen_names = {}, set()
        last = 0
        for step in steps:
            _mapping(step, "job step")
            number = _integer(step.get("number"), "step number", maximum=1000)
            name = step.get("name")
            if (number <= last or not isinstance(name, str) or not name or name in seen_names
                    or step.get("status") != "completed"
                    or step.get("conclusion") not in {"success", "failure", "skipped"}):
                raise ContractError("fleet step inventory is incomplete or ambiguous")
            by_number[number] = step
            seen_names.add(name)
            last = number
            if step["conclusion"] != "skipped" and not (
                _time(job["started_at"]) <= _time(step.get("started_at"))
                <= _time(step.get("completed_at")) <= _time(job["completed_at"])):
                raise ContractError("fleet step timestamps lie outside its exact job")
        contract = self.contracts[package.package_slug]
        failed, probes = [], []
        for expected_step in [*contract["required"], contract["gate"]]:
            step = by_number.get(expected_step["number"])
            if step is None or (expected_step["name"] is not None and step["name"] != expected_step["name"]):
                raise ContractError("required fleet probe/gate is missing or renamed")
            state = step["conclusion"]
            # Only trusted names and finite statuses enter public feedback, never logs.
            observation = {"number": expected_step["number"], "name": expected_step["name"], "conclusion": state}
            probes.append(observation)
            if state != "success":
                failed.append(observation)
        if normalized["conclusion"] == "success" and (failed or any(s["conclusion"] == "failure" for s in steps)):
            raise ContractError("successful fleet job concealed a failed or skipped required probe")
        if normalized["conclusion"] == "failure" and not any(s["conclusion"] == "failure" for s in steps):
            raise ContractError("failed fleet job has no concrete failed step")
        return normalized, {"package_slug": package.package_slug, "workflow_path": package.workflow_path,
            "batch": batch.batch, "run_id": run["id"], "run_attempt": 1, "job_id": job["id"],
            "job_url": normalized["html_url"], "status": normalized["conclusion"], "required_steps": probes}

    def _collect(self, descriptor, batch, nonce, payload, directory):
        run_id = payload["id"]
        # Legacy aggregation has no prefetch suffix. Normalize only after the
        # full live name (including prefetch:none) has been authenticated above.
        normalized_payload = dict(payload, name=batch.workflow_name, display_title=exact.expected_run_title(
            batch, self._orchestration_id(descriptor), nonce))
        run = exact.validate_workflow_run_api(normalized_payload, definition=batch, repository=REPOSITORY,
            branch=descriptor["branch"], head_sha=descriptor["candidate_sha"],
            orchestration_id=self._orchestration_id(descriptor), dispatch_nonce=nonce)
        jobs = self._inventory(f"actions/runs/{run_id}/attempts/1/jobs", "jobs")
        expected_names = {exact.expected_job_name(p) for p in batch.packages} | {"summary"}
        if len(jobs) != len(expected_names) or {j.get("name") for j in jobs} != expected_names:
            raise ContractError("fleet job inventory differs from full registered batch")
        normalized_jobs, observations = [], []
        for package in batch.packages:
            listed = next(j for j in jobs if j["name"] == exact.expected_job_name(package))
            # Attempt-scoped job pages are authoritative API evidence; an extra
            # GET per package would consume thousands of shared quota requests.
            normalized, observation = self._job_observation(descriptor, batch, package, run, listed)
            normalized_jobs.append(normalized)
            observations.append(observation)
        summary = next(j for j in jobs if j["name"] == "summary")
        if any(summary.get(k) != v for k, v in {"run_id": run_id, "run_attempt": 1,
            "head_sha": descriptor["candidate_sha"], "head_branch": descriptor["branch"], "status": "completed",
            "labels": ["ubuntu-24.04-arm"], "runner_group_id": 0, "runner_group_name": "GitHub Actions"}.items()):
            raise ContractError("batch summary producer identity mismatch")
        summary_steps = summary.get("steps")
        if (not isinstance(summary_steps, list) or not summary_steps or len(summary_steps) > 200
                or any(not isinstance(s, dict) or type(s.get("number")) is not int
                       or s.get("status") != "completed"
                       or s.get("conclusion") not in {"success", "failure", "skipped"} for s in summary_steps)
                or len({s["number"] for s in summary_steps}) != len(summary_steps)
                or summary.get("conclusion") not in {"success", "failure"}):
            raise ContractError("batch summary producer steps missing")
        producer_passed = True
        for required in self.summary_contracts[batch.batch]:
            matches = [s for s in summary_steps if isinstance(s, dict) and s.get("number") == required["number"]
                       and s.get("name") == required["name"]]
            if len(matches) != 1:
                raise ContractError("collector, attester or uploader identity is missing or duplicated")
            if matches[0]["conclusion"] != "success":
                producer_passed = False
        if not producer_passed and (summary["conclusion"] != "failure"
                                   or not any(s["conclusion"] == "failure" for s in summary_steps)):
            raise ContractError("failed collector evidence contradicts summary job")
        if payload["conclusion"] == "failure" and not any(o["status"] == "failure" for o in observations) and summary["conclusion"] != "failure":
            raise ContractError("failed batch lacks an exact failed job")
        artifacts = self._inventory(f"actions/runs/{run_id}/artifacts", "artifacts")
        named = [a for a in artifacts if a.get("name") == batch.artifact_name]
        if len(named) > 1:
            raise ContractError("duplicate exact batch artifact")
        if not named:
            if payload["conclusion"] != "failure":
                raise ContractError("successful batch is missing its exact artifact")
            # API-authenticated negative evidence authorizes one confirmation,
            # never a passing result or invented artifact/manifest identity.
            return {"batch": batch.batch, "run_id": run_id, "run_attempt": 1, "dispatch_nonce": nonce,
                "status": "failure", "artifact_status": "missing" if producer_passed else "collector_failed",
                "record": None, "observations": observations}, None
        if not producer_passed:
            raise ContractError("artifact exists without a successful exact collector producer")
        record, archive = None, None
        artifact_status = "missing"
        if named:
            artifact = exact.select_exact_artifact([{"total_count": len(artifacts), "artifacts": artifacts}],
                definition=batch, run=run)
            raw = self.api(f"repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip", raw=True)
            if (not isinstance(raw, bytes) or len(raw) != artifact["size_in_bytes"]
                    or "sha256:" + hashlib.sha256(raw).hexdigest() != artifact["digest"]):
                raise ContractError("fleet artifact size/digest mismatch")
            archive = directory / f"batch-{batch.batch}-{run_id}.zip"
            with archive.open("xb") as stream:
                stream.write(raw)
            record = exact.build_manifest_batch(definition=batch, dispatch_nonce=nonce, run=run,
                                               jobs=normalized_jobs, artifact=artifact)
            artifact_status = "verified"
        if payload["conclusion"] == "success" and (
                any(o["status"] != "success" for o in observations) or summary.get("conclusion") != "success" or not named):
            raise ContractError("successful batch lacks complete passing evidence")
        if payload["conclusion"] == "failure" and not any(o["status"] == "failure" for o in observations) and summary.get("conclusion") != "failure":
            raise ContractError("failed batch lacks an exact failed job")
        self._artifact_proof(descriptor, batch, record, archive)
        return {"batch": batch.batch, "run_id": run_id, "run_attempt": 1, "dispatch_nonce": nonce,
                "status": payload["conclusion"], "artifact_status": artifact_status,
                "record": record, "observations": observations}, archive

    def _artifact_proof(self, descriptor, batch, record, archive):
        raw = archive.read_bytes()
        if (len(raw) != record["artifact"]["size_in_bytes"]
                or "sha256:" + hashlib.sha256(raw).hexdigest() != record["artifact"]["digest"]):
            raise ContractError("candidate artifact changed after download")
        with tempfile.TemporaryDirectory(prefix="fleet-batch-proof-") as temporary:
            root = Path(temporary)
            exact._extract_verified_archive(raw, root)
            sentinel = batch_attestation.verify_attestation(results_root=root,
                workflow_file=self.repository_root / batch.workflow_path, batch=batch.batch,
                repository=REPOSITORY, expected_branch=descriptor["branch"], current_branch=descriptor["branch"],
                expected_sha=descriptor["candidate_sha"], workflow_sha=descriptor["candidate_sha"],
                orchestration_id=self._orchestration_id(descriptor), dispatch_nonce=record["dispatch_nonce"],
                run_id=record["run"]["id"], run_attempt=1, artifact_name=batch.artifact_name)
            packages = []
            for registration, job, attested in zip(batch.packages, record["jobs"], sentinel["packages"], strict=True):
                payload = read_json(root / attested["result_path"], maximum=exact.MAX_RESULT_BYTES)
                if job["conclusion"] == "failure":
                    result = _failed_result(payload, registration=registration,
                        batch=batch.batch, run=record["run"], job=job)
                else:
                    result = exact.validate_package_result(payload, registration=registration, repository=REPOSITORY,
                        batch=batch.batch, run=record["run"], job=job)
                if result["run"]["status"] != job["conclusion"]:
                    raise ContractError("artifact package status contradicts live package job")
                if job["conclusion"] == "success" and (
                        any(detail["status"] != "passed" for detail in result["tests"]["details"][:5])
                        or result["metadata"]["regression_status"] not in {"passed", "not_applicable"}):
                    raise ContractError("candidate green cannot omit core probes or defer applicable regression")
                packages.append({"package_slug": registration.package_slug, "workflow_path": registration.workflow_path,
                    "job_id": job["id"], "run_status": result["run"]["status"], "sha256": attested["sha256"]})
            expected_conclusion = "failure" if any(p["run_status"] == "failure" for p in packages) else "success"
            if expected_conclusion != record["run"]["conclusion"]:
                raise ContractError("batch conclusion contradicts its complete package evidence")
            return {"batch": batch.batch, "run_id": record["run"]["id"], "run_attempt": 1,
                "artifact_id": record["artifact"]["id"], "artifact_digest": record["artifact"]["digest"],
                "attestation_sha256": hashlib.sha256((root / batch_attestation.SENTINEL_NAME).read_bytes()).hexdigest(),
                "packages": packages}

    def _finish(self, descriptor, topology, selected, history, archives, completed_at):
        manifest, attestation = None, None
        records = [selected[b.batch]["record"] for b in topology]
        if not all(records):
            raise ContractError("selected fleet evidence is incomplete; no admissible repair feedback")
        evidence_status = "incomplete"
        if all(records):
            candidate = {"schema": exact.MANIFEST_SCHEMA, "version": exact.MANIFEST_VERSION,
                "repository": REPOSITORY, "branch": descriptor["branch"], "head_sha": descriptor["candidate_sha"],
                "topology_sha256": exact.topology_sha256(topology), "orchestration_id": self._orchestration_id(descriptor),
                "created_at": completed_at, "batches": records}
            manifest = exact.validate_manifest(candidate, topology=topology, expected_repository=REPOSITORY,
                expected_branch=descriptor["branch"], expected_sha=descriptor["candidate_sha"],
                expected_orchestration_id=self._orchestration_id(descriptor),
                expected_dispatch_nonces=[selected[b.batch]["dispatch_nonce"] for b in topology],
                expected_not_before=self.started.strftime("%Y-%m-%dT%H:%M:%SZ"), expected_not_after=completed_at)
            proofs = [self._artifact_proof(descriptor, b, selected[b.batch]["record"],
                      archives[(b.batch, selected[b.batch]["run_id"])]) for b in topology]
            attestation = {"schema_version": 1, "kind": "candidate-fleet-artifact-attestation",
                "descriptor": descriptor, "manifest_sha256": hashlib.sha256(
                    (exact.canonical_json(manifest) + "\n").encode("ascii")).hexdigest(),
                "batches": proofs, "overall_status": "failure" if any(p["run_status"] == "failure"
                    for proof in proofs for p in proof["packages"]) else "success"}
            evidence_status = "complete"
        status = "success" if all(selected[b.batch]["status"] == "success" for b in topology) else "failure"
        if status == "success" and (evidence_status != "complete" or attestation["overall_status"] != "success"):
            raise ContractError("fleet cannot be green without complete exact aggregate evidence")
        observations = [o for b in topology for o in selected[b.batch]["observations"]]
        summary = {"kind": "candidate-global-summary", "publishing": False, "status": status,
            "evidence_status": evidence_status, "candidate_sha": descriptor["candidate_sha"],
            "batch_count": len(topology), "package_count": len(observations),
            "passed_packages": sum(o["status"] == "success" for o in observations),
            "failed_packages": [o for o in observations if o["status"] == "failure"],
            "failed_batches": [b.batch for b in topology if selected[b.batch]["status"] != "success"],
            "accepted_runs": [{"batch": b.batch, "run_id": selected[b.batch]["run_id"], "run_attempt": 1,
                               "status": selected[b.batch]["status"]} for b in topology]}
        return {"schema_version": 1, "kind": "smoke-repair-candidate-fleet", "descriptor": descriptor,
            "publishing": False, "status": status, "topology_sha256": exact.topology_sha256(topology),
            "started_at": self.started.strftime("%Y-%m-%dT%H:%M:%SZ"), "completed_at": completed_at,
            "history": [history[b.batch] for b in topology], "manifest": manifest, "attestation": attestation,
            "summary": summary}

    def run(self, descriptor, *, repository_root, bundle_receipt, attest_candidate):
        descriptor, topology = self._prepare(descriptor, repository_root, bundle_receipt, attest_candidate)
        self.started = _time(self.now())
        self.nonces = set()
        history = {b.batch: [] for b in topology}
        selected, archives, pending = {}, {}, {}
        with tempfile.TemporaryDirectory(prefix="candidate-fleet-") as temporary:
            root = Path(temporary)
            for batch in topology:
                pending[batch.batch] = self._dispatch(descriptor, batch, [])
            for _ in range(self.max_polls):
                self._current(descriptor)
                for batch in topology:
                    if batch.batch not in pending:
                        continue
                    nonce = pending[batch.batch]
                    run = self._select(descriptor, batch, nonce)
                    if run is None or run["status"] != "completed":
                        continue
                    observation, archive = self._collect(descriptor, batch, nonce, run, root)
                    history[batch.batch].append(observation)
                    archives[(batch.batch, run["id"])] = archive
                    if observation["status"] == "failure" and len(history[batch.batch]) == 1:
                        pending[batch.batch] = self._dispatch(descriptor, batch, history[batch.batch])
                    else:
                        selected[batch.batch] = observation
                        del pending[batch.batch]
                if not pending:
                    self._attest(descriptor, bundle_receipt, repository_root, attest_candidate)
                    # Recheck registration and attempt identity after all downloads.
                    for batch in topology:
                        self._recheck_history(descriptor, batch, history[batch.batch])
                    receipt = self._finish(descriptor, topology, selected, history, archives, self.now())
                    self._current(descriptor)
                    return receipt
                self.sleep(min(self.poll_interval, self.remaining()))
            raise ContractError("fleet polling budget exhausted; not passed")

    def _recheck_history(self, descriptor, batch, history):
        rows = self._runs(descriptor, batch)
        if {r["id"] for r in rows} != {r["run_id"] for r in history}:
            raise ContractError("fleet run inventory changed after validation")
        for entry in history:
            run = self._select(descriptor, batch, entry["dispatch_nonce"], entry["run_id"])
            if run is None or run.get("status") != "completed" or run.get("conclusion") != entry["status"]:
                raise ContractError("fleet terminal run changed after validation")

    def verify(self, descriptor, receipt, *, repository_root, bundle_receipt, attest_candidate):
        if self.session is not None:
            self.remaining()
            receipt = _mapping(receipt, "fleet receipt")
            started, completed = _time(receipt.get("started_at")), _time(receipt.get("completed_at"))
            if (not started <= completed <= _time(self.now())
                    or (_time(self.now()) - started).total_seconds() > 86400
                    or (completed - started).total_seconds() > MAX_SECONDS):
                raise ContractError("fleet receipt is stale or has invalid timestamps")
            identity = {"descriptor": descriptor, "receipt": receipt, "bundle": bundle_receipt}
            # Keep the worker's accounting and deadline in the read path. The
            # recorder sits beneath this worker while the existing verifier runs.
            def build(_reader):
                original = self.github
                self.github = self.session.reader(original)
                try:
                    return self._verify(descriptor, receipt, repository_root=repository_root,
                        bundle_receipt=bundle_receipt, attest_candidate=attest_candidate)
                finally:
                    self.github = original
            result = self.session.verify("candidate-fleet", identity, self, build,
                root=repository_root, now=self.wall_clock(),
                window=(completed.timestamp(), started.timestamp() + 86400))
            self.remaining()
            return result
        return self._verify(descriptor, receipt, repository_root=repository_root,
            bundle_receipt=bundle_receipt, attest_candidate=attest_candidate)

    def _verify(self, descriptor, receipt, *, repository_root, bundle_receipt, attest_candidate):
        descriptor, topology = self._prepare(descriptor, repository_root, bundle_receipt, attest_candidate)
        receipt = _mapping(receipt, "fleet receipt")
        if (set(receipt) != RECEIPT_KEYS or type(receipt.get("schema_version")) is not int
                or receipt["schema_version"] != 1 or receipt["kind"] != "smoke-repair-candidate-fleet"
                or receipt["publishing"] is not False or receipt["status"] not in {"success", "failure"}):
            raise ContractError("unsupported candidate fleet receipt")
        _same(receipt["descriptor"], descriptor, "receipt candidate")
        self.started = _time(receipt["started_at"])
        completed = _time(receipt["completed_at"])
        if not self.started <= completed <= _time(self.now()) or (_time(self.now()) - self.started).total_seconds() > 86400:
            raise ContractError("fleet receipt is stale or has invalid timestamps")
        if (completed - self.started).total_seconds() > MAX_SECONDS:
            raise ContractError("fleet receipt exceeds bounded validation window")
        rows = receipt["history"]
        if not isinstance(rows, list) or len(rows) != len(topology):
            raise ContractError("fleet receipt does not cover every registered batch")
        history, selected, archives = {}, {}, {}
        seen_runs, seen_nonces = set(), set()
        with tempfile.TemporaryDirectory(prefix="verify-candidate-fleet-") as temporary:
            for batch, entries in zip(topology, rows, strict=True):
                if not isinstance(entries, list) or not 1 <= len(entries) <= 2:
                    raise ContractError("fleet receipt exceeds single-confirmation budget")
                history[batch.batch] = []
                for index, entry in enumerate(entries):
                    _mapping(entry, "fleet history")
                    if index == 1 and entries[0].get("status") != "failure":
                        raise ContractError("fleet receipt retried a passing batch")
                    nonce = orchestration.validate_dispatch_nonce(entry.get("dispatch_nonce"))
                    run_id = _integer(entry.get("run_id"), "fleet run ID")
                    if run_id in seen_runs or nonce in seen_nonces:
                        raise ContractError("fleet receipt reuses an exact identity")
                    seen_runs.add(run_id)
                    seen_nonces.add(nonce)
                    run = self._select(descriptor, batch, nonce, run_id)
                    if run is None or run["status"] != "completed":
                        raise ContractError("fleet receipt run is missing or incomplete")
                    observed, archive = self._collect(descriptor, batch, nonce, run, Path(temporary))
                    _same(observed, entry, "fleet history")
                    history[batch.batch].append(observed)
                    archives[(batch.batch, run_id)] = archive
                if entries[-1]["status"] == "failure" and len(entries) != 2:
                    raise ContractError("failed fleet batch has not received its one confirmation")
                selected[batch.batch] = history[batch.batch][-1]
                self._recheck_history(descriptor, batch, history[batch.batch])
            self._attest(descriptor, bundle_receipt, repository_root, attest_candidate)
            rebuilt = self._finish(descriptor, topology, selected, history, archives, receipt["completed_at"])
            _same(rebuilt, receipt, "candidate global summary")
            self._current(descriptor)
            return rebuilt


def _bundle_attestor(descriptor, bundle_receipt, *, api, repository_root):
    # This import is resolved exclusively beside this trusted-main script. Never
    # accept a module path from callback JSON, candidate code or CLI arguments.
    from smoke_repair_bundle import attest_candidate
    return attest_candidate(descriptor, bundle_receipt, api=api, repository_root=repository_root)


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
    parser.add_argument("mode", choices=("run", "verify"))
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--bundle-receipt", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "verify" and args.receipt is None:
            raise ContractError("verification requires a receipt")
        descriptor = validate_descriptor(read_json(args.descriptor))
        # The write-capable controller itself must execute trusted main, first attempt.
        if any(os.environ.get(k) != v for k, v in {
            "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": descriptor["base_sha"], "GITHUB_RUN_ATTEMPT": "1",
        }.items()):
            raise ContractError("fleet controller is not trusted first-attempt main")
        bundle = read_json(args.bundle_receipt)
        args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        validator = FleetValidation(timeout_seconds=VERIFY_SECONDS if args.mode == "verify" else MAX_SECONDS,
                                    session=VerificationSession())
        options = {"repository_root": args.repository_root, "bundle_receipt": bundle,
                   "attest_candidate": _bundle_attestor}
        if args.mode == "run":
            result = validator.run(descriptor, **options)
        else:
            result = validator.verify(descriptor, read_json(args.receipt), **options)
        for name, payload in (("receipt.json", result), ("summary.json", result["summary"]),
                              ("manifest.json", result["manifest"]), ("attestation.json", result["attestation"])):
            write_json(args.output_dir / name, payload)
        print(orchestration.canonical_json({"status": result["status"], "publishing": False}))
        return 0
    except (ContractError, exact.ContractError, batch_attestation.AttestationError, OSError, ValueError, ImportError):
        # No exception strings: provider/API output may carry private metadata.
        print('{"status":"incomplete","publishing":false}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
