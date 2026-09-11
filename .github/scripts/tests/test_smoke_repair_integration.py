"""Offline recovery integration: real controllers/validators, fake storage and APIs.

The actual Zlib workflow is never executed. Actions observations are fixtures,
not a mocked native verdict: dispatch and both publisher verification passes run
NativeValidation. Git/catalog acquisition and transport are the only fakes.
"""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[2]
sys.path.insert(0, str(DIRECTORY.parent))
sys.path.insert(0, str(DIRECTORY))

import exact_run_aggregation as exact
import orchestration_contract as orchestration
import smoke_recovery as recovery
import smoke_repair_evidence as evidence
import smoke_repair_model as model
import smoke_repair_native as native
import smoke_repair_pipeline as pipeline
import smoke_repair_policy as policy
import test_smoke_recovery as recovery_fixture
import test_smoke_repair_evidence as evidence_fixture
import test_smoke_repair_model as model_fixture
import test_smoke_repair_native as native_fixture
import test_smoke_repair_publisher as publisher_fixture

publisher = publisher_fixture.module
REPOSITORY, BASE = recovery_fixture.REPOSITORY, recovery_fixture.SHA
WORKFLOW = ".github/workflows/test-zlib.yml"
BATCH = ".github/workflows/test-all-packages-batch3.yml"
PARENT_ID, CONFIRMATION_ID, ARTIFACT_ID = 123456, 20003, 55
RUN_ID, JOB_ID, WORKFLOW_ID = native_fixture.RUN_ID, native_fixture.JOB_ID, native_fixture.WORKFLOW_ID
REAL_RUN, REAL_POPEN = subprocess.run, subprocess.Popen


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utc(seconds):
    return (datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


class IntegrationAPI(publisher_fixture.FakeGitHub):
    """One fake service binds publisher Git objects to native API observations."""

    def __init__(self, git, failures, flow, *, workflow_path=WORKFLOW):
        super().__init__(git)
        self.failures, self.flow = failures, flow
        self.workflow_path = workflow_path
        self.reads, self.dispatches, self.events = [], [], []
        self.native_runs = []
        self.native_job = None
        self.before_dispatch = None
        self.ambiguous_post = False
        self.mutate_native = None
        self.before_native_read = None

    def _source(self, sha, path):
        blob = self.git.commits[sha]["entries"][path][1]
        raw = self.git.blobs[blob].encode()
        return {"type": "file", "path": path, "encoding": "base64", "size": len(raw),
                "sha": blob, "content": base64.b64encode(raw).decode()}

    def _native_observations(self, branch):
        sha = self.git.branches[branch]
        template = native_fixture.GitHubFixture()
        run = template.run
        run.update(path=self.workflow_path, head_sha=sha, head_branch=branch,
                   repository={"full_name": REPOSITORY}, head_repository={"full_name": REPOSITORY},
                   head_commit={"id": sha}, name=self.flow["name"],
                   url=f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}",
                   html_url=f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}",
                   created_at=utc(0), run_started_at=utc(5), updated_at=utc(200))
        called_job, source_job = next(iter(self.flow["jobs"].items()))
        job = template.job
        names = ["Set up job"] + [step["name"] for step in source_job["steps"]]
        job.update(head_sha=sha, head_branch=branch, name=source_job.get("name", called_job),
                   workflow_name=self.flow["name"], run_url=run["url"],
                   url=f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{JOB_ID}",
                   html_url=f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}/job/{JOB_ID}",
                   started_at=utc(10), completed_at=utc(100),
                   steps=[{"name": name, "number": index + 1, "status": "completed", "conclusion": "success",
                           "started_at": utc(10 + index * 2), "completed_at": utc(12 + index * 2)}
                          for index, name in enumerate(names)])
        job["steps"].append({"name": "Complete job", "number": len(names) + 3, "status": "completed",
                             "conclusion": "success", "started_at": utc(80), "completed_at": utc(80)})
        self.native_runs, self.native_job = [run], job
        if self.mutate_native:
            self.mutate_native(run, job)

    def api(self, endpoint, *, payload=None, **options):
        self.reads.append((endpoint, deepcopy(options)))
        if endpoint == "rate_limit" and payload is None:
            return {"resources": {"core": {"limit": 1000, "remaining": 1000, "reset": int(time.time()) + 3600}}}
        if not endpoint.startswith(f"repos/{REPOSITORY}") or endpoint.startswith("https:"):
            raise AssertionError(f"unexpected API authority: {endpoint}")
        prefix = f"repos/{REPOSITORY}/"
        route = urlsplit(endpoint)
        path, query = route.path.removeprefix(prefix), parse_qs(route.query)
        workflow_api = f"actions/workflows/{Path(self.workflow_path).name}"
        if payload is not None:
            if path != workflow_api + "/dispatches" or set(payload) != {"ref"}:
                raise AssertionError("only the original workflow's ref-only dispatch is authorized")
            if payload["ref"] not in self.git.branches or self.dispatches:
                raise AssertionError("native must dispatch the staged unique branch once")
            if self.before_dispatch:
                self.before_dispatch()
            self.dispatches.append(deepcopy(payload))
            self.events.append("dispatch")
            self._native_observations(payload["ref"])
            if self.ambiguous_post:
                raise orchestration.ContractError("synthetic ambiguous POST")
            return {"workflow_run_id": RUN_ID,
                    "run_url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}",
                    "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}"}
        if path.startswith("git/ref/heads/"):
            branch = path.removeprefix("git/ref/heads/")
            sha = self.git.remote_main if branch == "main" else self.git.branches[branch]
            return recovery_fixture.branch_ref(sha, branch)
        if endpoint in self.failures.responses or endpoint.endswith("/logs"):
            return self.failures.api(endpoint, **options)
        if self.before_native_read:
            self.before_native_read(path)
        if path.startswith("contents/"):
            return self._source(query["ref"][0], path.removeprefix("contents/"))
        if path.startswith("git/commits/"):
            sha = path.removeprefix("git/commits/")
            commit = self.git.commits[sha]
            return {"sha": sha, "tree": {"sha": self.git.tree(commit["entries"])},
                    "parents": [{"sha": parent} for parent in commit["parents"]]}
        if path == workflow_api:
            return {"id": WORKFLOW_ID, "path": self.workflow_path, "name": self.flow["name"], "state": "active"}
        if path in (workflow_api + "/runs", f"actions/runs/{RUN_ID}/attempts/1/jobs"):
            if options.get("pages") or query.get("per_page") != ["100"]:
                raise AssertionError("native pagination must be explicit and bounded")
            if path.endswith("/runs"):
                key, rows = "workflow_runs", self.native_runs
                branch = query["branch"][0]
                if query["head_sha"] != [self.git.branches[branch]] or "event" in query:
                    raise AssertionError("native run search must cover every event at the exact stage")
            else:
                key, rows = "jobs", [self.native_job] if self.native_job is not None else []
            start = (int(query["page"][0]) - 1) * 100
            return {"total_count": len(rows), key: deepcopy(rows[start:start + 100])}
        if path == f"actions/runs/{RUN_ID}":
            return deepcopy(self.native_runs[0])
        if path == f"actions/jobs/{JOB_ID}":
            self.events.append("authenticate-job")
            return deepcopy(self.native_job)
        raise AssertionError(f"unexpected API route: {endpoint}")

    def create_pull_request(self, config, *, body, head_sha):
        self.events.append("create-draft")
        return super().create_pull_request(config, body=body, head_sha=head_sha)


class SmokeRepairIntegrationTests(unittest.TestCase):
    def start(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "checkout"
        self.artifacts = Path(temporary.name).resolve() / "artifacts"
        self.root.mkdir()
        self.artifacts.mkdir()
        self.source = (ROOT / WORKFLOW).read_text()
        self.flow = exact._yaml_mapping(self.source.encode(), "real supported package")
        batch_source = (ROOT / BATCH).read_text()
        batch_flow = exact._yaml_mapping(batch_source.encode(), "real package registration")
        callers = [name for name, job in batch_flow["jobs"].items() if job.get("uses") == f"./{WORKFLOW}"]
        self.assertEqual(callers, ["test-zlib"])
        called_job = next(iter(self.flow["jobs"]))
        registration = exact.PackageRegistration(callers[0], called_job, WORKFLOW, "zlib")
        self.topology = tuple(replace(recovery_fixture.definition(number), packages=(registration,)) if number == 3
                              else recovery_fixture.definition(number) for number in range(1, 23))
        self.snapshot = {WORKFLOW: self.source.encode(), BATCH: batch_source.encode()}
        self.lock = {"schema_version": 3, "hardened_workflow_sha256": publisher.supply.workflow_snapshot_sha256(self.snapshot),
                     "hardened_topology_sha256": "d" * 64, "updated_at": "unchanged", "actions": [],
                     "containers": [], "permission_exceptions": []}
        self.files = {WORKFLOW: self.source, BATCH: batch_source, publisher.LOCK_PATH: json.dumps(self.lock) + "\n"}
        for relative, text in self.files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.start(patch.object(publisher_fixture, "REPOSITORY", REPOSITORY))
        self.git = publisher_fixture.FakeGit(self.root, self.files)
        self.failures = evidence_fixture.EvidenceFixture()
        self.failures.original = self.failures.manifest["batches"][2]
        self.failures.replacement = dict(self.failures.original, run_id=CONFIRMATION_ID, dispatch_nonce="f" * 64)
        self.failures.audit["failed_batches"] = [3]
        for index, record in enumerate((self.failures.original, self.failures.replacement)):
            self.failures.audit["history"][index].update(batch=3, run_id=record["run_id"])
            run = recovery_fixture.run_payload(record, "failure")
            job = recovery_fixture.job_payload(record, conclusion="failure")
            job["name"] = exact.expected_job_name(registration)
            job["steps"][0]["name"] = "Install Zlib"
            prefix = f"repos/{REPOSITORY}/actions/runs/{record['run_id']}"
            self.failures.responses[prefix] = run
            self.failures.responses[prefix + "/attempts/1/jobs?per_page=100"] = [{"total_count": 2, "jobs": [
                job, recovery_fixture.job_payload(record, summary=True)]}]
        self.failures.audit["dispatches"][0].update(batch=3, run_id=CONFIRMATION_ID)
        self.api = IntegrationAPI(self.git, self.failures, self.flow)
        self.clock = native_fixture.Clock()
        install = next(step for step in self.flow["jobs"][called_job]["steps"] if step.get("id") == "install")
        old = "          " + install["run"].splitlines()[0]
        self.proposal = {"diagnosis": "Bound build parallelism while retaining the native probes and final gate.",
                         "edits": [{"path": WORKFLOW, "old": old,
                                    "new": "          export CMAKE_BUILD_PARALLEL_LEVEL=2\n" + old}],
                         "unresolved_reason": ""}
        self.transport = model_fixture.StubTransport(model_fixture.wire(model_fixture.envelope(self.proposal)))
        self.command_calls = []
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GH_TOKEN": "fixture-only-not-a-credential",
            "SMOKE_REPAIR_APP_BOT_LOGIN": "repair[bot]", "SMOKE_REPAIR_APP_SLUG": "repair",
            "DASHBOARD_DELIVERY_APP_BOT_LOGIN": "generated[bot]", "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": BASE, "GITHUB_WORKFLOW_SHA": BASE,
            "GITHUB_RUN_ID": str(PARENT_ID), "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{evidence.ORCHESTRATOR_PATH}@refs/heads/main",
            "SMOKE_REPAIR_OPENAI_API_KEY": model_fixture.KEY, "SMOKE_REPAIR_MODEL": model_fixture.MODEL,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.start(patch.dict(os.environ, environment, clear=True))
        self.start(patch("socket.create_connection", side_effect=AssertionError("network forbidden")))
        self.start(patch.object(Path, "cwd", return_value=self.root))
        self.start(patch("subprocess.run", side_effect=self.run_command))
        self.start(patch("subprocess.Popen", side_effect=self.popen))
        self.start(patch.object(publisher.publisher, "Git", return_value=self.git))
        self.start(patch.object(publisher.publisher, "GhClient", return_value=self.api))
        self.start(patch.object(publisher.supply, "registered_workflows", return_value=[self.root / WORKFLOW]))
        self.start(patch.object(publisher.supply, "batch_paths", return_value=[self.root / BATCH]))
        self.start(patch.object(publisher.supply, "source_snapshot", side_effect=lambda *args: deepcopy(self.snapshot)))
        self.start(patch.object(publisher.supply, "load_lock", side_effect=lambda *args: deepcopy(self.lock)))
        self.start(patch.object(evidence, "discover_topology_at_commit", return_value=self.topology))
        for module in (evidence, recovery, native):
            self.start(patch.object(module, "GitHub", return_value=self.api))

    @staticmethod
    def allowed_process(command):
        return (command == ["bash", "--noprofile", "--norc", "-n"] or
                (len(command) == 5 and command[:3] == [sys.executable, "-I", "-B"]
                 and command[4] == "--help" and Path(command[3]).parent == DIRECTORY.parent
                 and Path(command[3]).name.startswith("smoke_repair_")))

    def popen(self, command, *args, **kwargs):
        if not self.allowed_process(command):
            raise AssertionError(f"actual process forbidden: {command}")
        return REAL_POPEN(command, *args, **kwargs)

    def run_command(self, command, **kwargs):
        self.command_calls.append((deepcopy(command), deepcopy(kwargs)))
        if self.allowed_process(command):
            self.assertNotIn("shell", kwargs)
            return REAL_RUN(command, **kwargs)
        prefix = ["git", "-C", str(self.root)]
        if command[:3] != prefix:
            raise AssertionError(f"unexpected subprocess: {command}")
        tail = command[3:]
        if tail == ["rev-parse", "--verify", "HEAD^{commit}"]:
            output = BASE + "\n"
        elif tail == ["status", "--porcelain=v1", "--untracked-files=all", "--", ".github/workflows", ".github/actions"]:
            output = ""
        elif tail == ["show", f"{BASE}:{WORKFLOW}"]:
            self.assertEqual(kwargs["env"]["GIT_NO_REPLACE_OBJECTS"], "1")
            output = self.source
        elif tail == ["cat-file", "-s", f"{BASE}:{WORKFLOW}"]:
            output = str(len(self.source.encode()))
        else:
            raise AssertionError(f"unexpected Git process: {command}")
        return subprocess.CompletedProcess(command, 0, output if kwargs.get("text") else output.encode(), "")

    def path(self, name):
        return self.artifacts / name

    def write(self, name, value):
        self.path(name).write_text(orchestration.canonical_json(value) + "\n")

    def read(self, name):
        return orchestration.decode_json(self.path(name).read_bytes())

    def invoke(self, module, args, *, expected=0):
        with patch("sys.stderr", new_callable=io.StringIO) as errors, patch("sys.stdout", new_callable=io.StringIO):
            result = module.main([str(value) for value in args])
        self.assertEqual(result, expected, errors.getvalue())
        return errors.getvalue()

    def collect(self, *, expected=0):
        raw = evidence_fixture.ParentAndArchiveTests.archive([("recovery-audit.json", json.dumps(self.failures.audit))])
        endpoint = f"repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}"
        self.failures.responses[endpoint] = {"id": ARTIFACT_ID, "name": f"smoke-orchestration-evidence-{PARENT_ID}-1",
            "expired": False, "workflow_run": {"id": PARENT_ID, "head_sha": BASE, "head_branch": "main"},
            "created_at": recovery_fixture.STEP_END, "size_in_bytes": len(raw), "digest": f"sha256:{digest(raw)}"}
        self.failures.responses[endpoint + "/zip"] = raw
        self.invoke(evidence, ["--repository", REPOSITORY, "--base-sha", BASE, "--run-id", PARENT_ID,
                              "--attempt", 1, "--artifact-id", ARTIFACT_ID, "--output", self.path("bundle.json")], expected=expected)
        if expected:
            return None
        self.invoke(pipeline, ["select", "--bundle", self.path("bundle.json"), "--slug", "zlib",
                              "--repository", REPOSITORY, "--base-sha", BASE, "--output", self.path("context.json"),
                              "--model-output", self.path("model-context.json")])
        return self.read("context.json")

    def propose(self):
        # Only transport is replaced: build_request/propose/parse_response remain real.
        real_propose = model.propose
        with patch.object(model, "propose", side_effect=lambda context, **kwargs:
                          real_propose(context, transport=self.transport, **kwargs)):
            self.invoke(model, ["--context", self.path("model-context.json"), "--output", self.path("proposal.json")])
        return self.read("proposal.json")

    def admit(self):
        self.invoke(pipeline, ["admit", "--context", self.path("context.json"), "--proposal", self.path("proposal.json"),
                              "--source-output", self.path("candidate.yml"), "--contract-output", self.path("contract.json")])
        self.invoke(publisher, ["admit", *self.publisher_args(), "--output", self.path("candidate.json")])
        return self.read("candidate.json")

    def publisher_args(self):
        return ["--context", self.path("context.json"), "--proposal", self.path("proposal.json"),
                "--repository-root", self.root, "--policy-version", policy.POLICY_VERSION]

    def stage(self, *, expected=0):
        self.invoke(publisher, ["stage", *self.publisher_args(), "--candidate", self.path("candidate.json"),
                               "--native-contract", self.path("contract.json"), "--output", self.path("stage.json")],
                    expected=expected)
        return self.read("stage.json") if expected == 0 else None

    def dispatch(self, *, expected=0):
        self.invoke(native, ["--mode", "dispatch", "--stage", self.path("stage.json"),
                            "--contract", self.path("contract.json"), "--output", self.path("native.json")], expected=expected)
        return self.read("native.json")

    def publish(self, *, expected=0):
        self.invoke(publisher, ["open-pr", *self.publisher_args(), "--stage", self.path("stage.json"),
                               "--native-contract", self.path("contract.json"), "--native-receipt", self.path("native.json"),
                               "--output", self.path("result.json")], expected=expected)
        return self.read("result.json") if expected == 0 else None

    def staged(self):
        self.collect()
        self.propose()
        self.admit()
        return self.stage()

    def test_actual_evidence_model_policy_publisher_native_and_draft_clis(self):
        context = self.collect()
        self.assertEqual(context["source_text"], self.source)
        self.assertEqual(context["package_slug"], "zlib")
        self.assertEqual(context["initial_run_id"], 10003)
        self.assertEqual(context["confirmation_run_id"], CONFIRMATION_ID)
        self.assertEqual(context["failed_steps"], ["Install Zlib"])
        self.assertIn("credential-bearing", context["log_excerpt"])
        self.assertNotIn("Authorization:", context["log_excerpt"])
        proposal = self.propose()
        self.assertEqual(proposal, self.proposal)
        request = orchestration.decode_json(self.transport.calls[0][0])
        self.assertEqual(request["tools"], [])
        self.assertIs(request["text"]["format"]["strict"], True)
        self.assertEqual(orchestration.decode_json(request["input"][1]["content"]), self.read("model-context.json"))
        self.assertNotIn("orchestrator_run_id", self.read("model-context.json"))
        candidate = self.admit()
        contract = self.read("contract.json")
        self.assertEqual(candidate["candidate_source"], self.path("candidate.yml").read_text())
        self.assertEqual(contract["source_digest"], candidate["policy_result"]["candidate_source_sha256"])
        self.assertEqual(contract["mandatory_steps"], candidate["policy_result"]["contract"]["mandatory_step_names"])
        self.assertEqual(contract["gate_step"], "Calculate test summary")
        self.assertIn("Regression applicability - package manager installed", contract["mandatory_steps"])
        self.assertIs(candidate["policy_result"]["review_required"], True)
        self.assertIs(candidate["policy_result"]["semantic_equivalence_proven"], False)
        self.assertEqual(self.api.calls, [])
        stage = self.stage()
        self.assertEqual(stage["branch"], f"automation/smoke-repair/{PARENT_ID}-1-zlib")
        self.assertEqual(set(stage), publisher.STAGE_KEYS)
        self.assertEqual(self.api.prs, [])
        self.assertEqual(self.api.dispatches, [])
        self.assertEqual(self.git.entries, self.git.base_entries)
        native_receipt = self.dispatch()
        self.assertEqual(native_receipt["stage"], stage)
        self.assertEqual(native_receipt["status"], "passed")
        self.assertEqual(native_receipt["job"]["name"], "test-zlib")
        self.assertEqual(native_receipt["steps"], self.api.native_job["steps"])
        self.assertNotIn("tests_passed", native_receipt)
        self.assertEqual(self.api.dispatches, [{"ref": stage["branch"]}])
        self.invoke(native, ["--mode", "verify", "--stage", self.path("stage.json"), "--contract", self.path("contract.json"),
                            "--receipt", self.path("native.json"), "--output", self.path("verified.json")])
        self.assertEqual(self.read("verified.json"), native_receipt)
        result = self.publish()
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["native_run_id"], RUN_ID)
        self.assertEqual(len(self.api.prs), 1)
        pr = self.api.prs[0]
        self.assertIs(pr["draft"], True)
        self.assertEqual(pr["head"]["sha"], stage["candidate_sha"])
        self.assertIn(f"actions/runs/{CONFIRMATION_ID}", pr["body"])
        self.assertIn(native_receipt["run"]["html_url"], pr["body"])
        self.assertGreaterEqual(self.api.events[:self.api.events.index("create-draft")].count("authenticate-job"), 4)
        self.assertEqual(self.source, (self.root / WORKFLOW).read_text())
        self.assertFalse(any(call[0] in {"push", "commit", "commit-tree", "checkout", "switch"} for call in self.git.calls))
        self.assertTrue(any(command == ["bash", "--noprofile", "--norc", "-n"] for command, _ in self.command_calls))

    def test_supported_base_metadata_matches_both_contract_derivations(self):
        context = self.collect()
        self.propose()
        result = policy.validate_proposal(context, self.proposal)
        contract = native.derive_native_contract(self.source.encode(), repository=REPOSITORY, base_sha=BASE,
            workflow_path=WORKFLOW, package_slug="zlib", called_job=context["called_job"],
            source_digest=result["candidate_source_sha256"])
        self.assertEqual(contract["job_name"], result["contract"]["expected_job_name"])
        self.assertEqual(contract["mandatory_steps"], result["contract"]["mandatory_step_names"])
        self.assertEqual(contract["gate_step"], result["contract"]["final_gate_step_name"])
        changed = exact._yaml_mapping(result["candidate_source"].encode(), "admitted source")
        original_steps = self.flow["jobs"]["test-zlib"]["steps"]
        changed_steps = changed["jobs"]["test-zlib"]["steps"]
        for before, after in zip(original_steps, changed_steps, strict=True):
            if before.get("id") != "install":
                self.assertEqual(before, after)

    def test_wrong_confirmation_sha_stops_before_model_or_stage(self):
        endpoint = f"repos/{REPOSITORY}/actions/runs/{CONFIRMATION_ID}"
        self.failures.responses[endpoint]["head_sha"] = "e" * 40
        self.collect(expected=1)
        self.assertFalse(self.path("context.json").exists())
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.api.calls, [])
        self.assertEqual(self.api.dispatches, [])

    def test_structured_model_cannot_authorize_a_gate_edit(self):
        self.collect()
        gate = next(step for step in self.flow["jobs"]["test-zlib"]["steps"] if step.get("id") == "summary")
        proposal = {"diagnosis": "Untrusted suggestion", "edits": [{"path": WORKFLOW,
                    "old": gate["run"].splitlines()[0], "new": "exit 0"}], "unresolved_reason": ""}
        self.transport.response = model_fixture.wire(model_fixture.envelope(proposal))
        self.assertEqual(self.propose(), proposal)
        self.invoke(pipeline, ["admit", "--context", self.path("context.json"), "--proposal", self.path("proposal.json"),
                              "--source-output", self.path("candidate.yml"), "--contract-output", self.path("contract.json")], expected=1)
        self.assertFalse(self.path("candidate.yml").exists())
        self.assertEqual(self.api.calls, [])

    def test_model_refusal_is_data_and_cannot_be_staged(self):
        self.collect()
        self.transport.response = model_fixture.wire(model_fixture.envelope(model_fixture.unresolved()))
        self.propose()
        self.invoke(publisher, ["admit", *self.publisher_args(), "--output", self.path("candidate.json")], expected=1)
        self.assertFalse(self.path("candidate.json").exists())
        self.assertEqual(self.api.calls, [])

    def test_modified_candidate_json_is_not_an_authorization_to_create_branch(self):
        self.collect()
        self.propose()
        candidate = self.admit()
        candidate["candidate_source"] += "# forged candidate\n"
        self.write("candidate.json", candidate)
        self.stage(expected=1)
        self.assertEqual(self.git.branches, {})
        self.assertEqual(self.api.calls, [])

    def test_modified_native_contract_is_rejected_before_branch_creation(self):
        self.collect()
        self.propose()
        self.admit()
        contract = self.read("contract.json")
        contract["mandatory_steps"] = contract["mandatory_steps"][:-1]
        self.write("contract.json", contract)
        self.stage(expected=1)
        self.assertEqual(self.git.branches, {})
        self.assertFalse(any(method != "GET" for method, _, _ in self.api.calls))

    def test_native_wrong_sha_never_yields_publishable_receipt(self):
        self.staged()
        self.api.mutate_native = lambda run, job: run.update(head_sha=BASE)
        self.assertEqual(self.dispatch(expected=1)["status"], "not_passed")
        self.publish(expected=1)
        self.assertEqual(self.api.prs, [])
        self.assertEqual(len(self.api.dispatches), 1)

    def test_skipped_mandatory_step_rejects_green_run_and_job(self):
        self.staged()
        required = self.read("contract.json")["mandatory_steps"][-1]
        def skip(run, job):
            next(step for step in job["steps"] if step["name"] == required)["conclusion"] = "skipped"
        self.api.mutate_native = skip
        self.dispatch(expected=1)
        self.publish(expected=1)
        self.assertEqual(self.api.prs, [])

    def test_native_ambiguous_post_is_reconciled_not_redispatched(self):
        self.staged()
        self.api.ambiguous_post = True
        self.assertEqual(self.dispatch()["status"], "passed")
        self.assertEqual(self.publish()["status"], "created")
        self.assertEqual(len(self.api.dispatches), 1)

    def test_publisher_reauthenticates_and_rejects_run_changed_after_receipt(self):
        self.staged()
        self.dispatch()
        self.api.native_runs[0]["run_attempt"] = 2
        self.publish(expected=1)
        self.assertEqual(self.api.prs, [])

    def test_publisher_reauthenticates_job_step_not_just_receipt_green_status(self):
        self.staged()
        self.dispatch()
        self.api.native_job["steps"][5]["conclusion"] = "failure"
        self.publish(expected=1)
        self.assertEqual(self.api.prs, [])

    def test_main_advance_between_native_and_publisher_prevents_draft(self):
        self.staged()
        self.dispatch()
        self.git.remote_main = "e" * 40
        self.publish(expected=1)
        self.assertEqual(self.api.prs, [])

    def test_real_verifier_is_called_again_immediately_before_draft_creation(self):
        self.staged()
        self.dispatch()
        checks = 0
        def change_on_second_verification(path):
            nonlocal checks
            if path == f"actions/jobs/{JOB_ID}":
                checks += 1
                if checks == 2:
                    self.api.native_job["steps"][5]["conclusion"] = "failure"
        self.api.before_native_read = change_on_second_verification
        self.publish(expected=1)
        self.assertEqual(checks, 2)
        self.assertEqual(self.api.prs, [])

    def test_every_controller_imports_in_the_workflows_isolated_python_mode(self):
        for filename in ("smoke_repair_evidence.py", "smoke_repair_model.py", "smoke_repair_pipeline.py",
                         "smoke_repair_publisher.py", "smoke_repair_native.py"):
            with self.subTest(controller=filename):
                result = subprocess.run([sys.executable, "-I", "-B", str(DIRECTORY.parent / filename), "--help"],
                                        capture_output=True, text=True, timeout=15,
                                        env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_workflow_arguments_are_accepted_by_controller_parsers(self):
        class Parsed(BaseException):
            def __init__(self, namespace):
                self.namespace = namespace
        original_parse = argparse.ArgumentParser.parse_args
        def parse_only(parser, args=None, namespace=None):
            raise Parsed(original_parse(parser, args, namespace))
        modules = {"smoke_repair_evidence.py": evidence, "smoke_repair_pipeline.py": pipeline,
                   "smoke_repair_model.py": model, "smoke_repair_publisher.py": publisher,
                   "smoke_repair_native.py": native}
        variables = {"REPOSITORY": REPOSITORY, "BASE_SHA": BASE, "PARENT_RUN_ID": str(PARENT_ID),
                     "PARENT_ATTEMPT": "1", "EVIDENCE_ARTIFACT_ID": str(ARTIFACT_ID),
                     "GITHUB_RUN_ID": str(PARENT_ID), "GITHUB_RUN_ATTEMPT": "1", "PACKAGE_SLUG": "zlib",
                     "RUNNER_TEMP": str(self.artifacts), "RECIPIENT": "fixture-owner"}
        seen = set()
        for workflow_name in ("smoke-repair.yml", "smoke-repair-package.yml"):
            flow = exact._yaml_mapping((ROOT / ".github/workflows" / workflow_name).read_bytes(), "repair controller workflow")
            for job in flow["jobs"].values():
                for step in job.get("steps", []):
                    for line in step.get("run", "").replace("\\\n", " ").splitlines():
                        if not line.strip().startswith("python3 "):
                            continue
                        tokens = shlex.split(line)
                        positions = [index for index, token in enumerate(tokens) if Path(token).name in modules]
                        if not positions:
                            continue
                        self.assertEqual(len(positions), 1)
                        position = positions[0]
                        filename = Path(tokens[position]).name
                        self.assertEqual(tokens[:position], ["python3", "-I", "-B"])
                        args = [re.sub(r"\$([A-Z_][A-Z_0-9]*)", lambda match: variables[match[1]], token)
                                for token in tokens[position + 1:]]
                        with self.subTest(workflow=workflow_name, step=step.get("name")), patch.object(
                                argparse.ArgumentParser, "parse_args", parse_only), self.assertRaises(Parsed) as parsed:
                            modules[filename].main(args)
                        namespace = parsed.exception.namespace
                        action = getattr(namespace, "command", getattr(namespace, "mode", "default"))
                        seen.add((filename, action))
                        if filename == "smoke_repair_publisher.py" and action == "stage":
                            self.assertEqual(namespace.candidate.suffix, ".json")
                            self.assertIsNotNone(namespace.native_contract)
                        if filename == "smoke_repair_publisher.py" and action == "open-pr":
                            self.assertIsNotNone(namespace.stage)
                            self.assertIsNotNone(namespace.native_contract)
        self.assertEqual(seen, {("smoke_repair_evidence.py", "default"), ("smoke_repair_model.py", "default"),
                               ("smoke_repair_pipeline.py", "select"), ("smoke_repair_pipeline.py", "admit"),
                               ("smoke_repair_pipeline.py", "report"), ("smoke_repair_publisher.py", "admit"),
                               ("smoke_repair_publisher.py", "stage"), ("smoke_repair_publisher.py", "open-pr"),
                               ("smoke_repair_native.py", "dispatch"), ("smoke_repair_native.py", "verify")})


class RegisteredNativeLayoutTests(unittest.TestCase):
    """Current layouts and the explicit nonmandatory-skip restriction, offline."""

    def layout(self, slug, *, conditional_diagnostic=False):
        path = f".github/workflows/test-{slug}.yml"
        raw = (ROOT / path).read_bytes()
        flow = exact._yaml_mapping(raw, "registered native layout")
        called_job, source_job = next(iter(flow["jobs"].items()))
        diagnostic = "Show regression validation details" if slug == "nginx" else "Set test metadata"
        if conditional_diagnostic:
            # In-memory baseline variant, not a claim about the checked-in source.
            step = next(step for step in source_job["steps"] if step["name"] == diagnostic)
            step["if"] = "failure()"
            raw = native_fixture.encode_source(flow)
        policy_contract = policy.derive_contract(raw.decode(), called_job)
        expected = native._derive_expectations(raw, repository=REPOSITORY, base_sha=BASE,
            workflow_path=path, package_slug=slug, called_job=called_job)
        self.assertEqual([step["name"] for step in expected["required_steps"]], policy_contract["mandatory_step_names"])
        self.assertEqual(expected["final_gate"]["name"], policy_contract["final_gate_step_name"])
        stage = dict(native_fixture.GitHubFixture().stage, repository=REPOSITORY,
                     repair_id=f"{PARENT_ID}-1-{slug}", branch=f"automation/smoke-repair/{PARENT_ID}-1-{slug}",
                     workflow_path=path, package_slug=slug, source_digest=digest(raw))
        native.validate_stage(stage)
        api = IntegrationAPI(SimpleNamespace(branches={stage["branch"]: stage["candidate_sha"]}),
                             None, flow, workflow_path=path)
        api._native_observations(stage["branch"])
        clock = native_fixture.Clock()
        validator = native.NativeValidation(api, clock=clock, sleep=clock.sleep)
        run = validator._run(stage, expected, WORKFLOW_ID, RUN_ID, api.native_runs[0])
        self.assertIsNotNone(validator._job(stage, expected, run, api.native_job))
        return validator, stage, expected, run, api.native_job, source_job, diagnostic

    def test_actual_ngspice_and_nginx_api_job_layouts_are_supported(self):
        for slug in ("ngspice", "nginx"):
            with self.subTest(slug=slug):
                validator, stage, contract, run, job, source_job, _ = self.layout(slug)
                observed, steps = validator._job(stage, contract, run, job)
                self.assertEqual(observed["name"], f"test-{slug}")
                self.assertEqual(steps, job["steps"])
                mandatory = {step["name"] for step in contract["required_steps"]} | {contract["final_gate"]["name"]}
                conditionals = [step["name"] for step in source_job["steps"]
                                if step["name"] not in mandatory and step.get("if") not in (None, "always()", "${{ always() }}")]
                self.assertEqual(conditionals, [], "a newly conditional baseline step needs an explicit skip-policy review")
                if slug == "ngspice":
                    applicability = next(step for step in source_job["steps"] if step.get("id") == "test6")
                    self.assertIn("status=skipped", applicability["run"])
                    observed_step = next(step for step in steps if step["name"] == applicability["name"])
                    self.assertEqual(observed_step["conclusion"], "success")

    def test_actual_diagnostic_skip_has_no_baseline_authorization(self):
        for slug in ("ngspice", "nginx"):
            with self.subTest(slug=slug):
                validator, stage, contract, run, job, _, diagnostic = self.layout(slug)
                step = next(step for step in job["steps"] if step["name"] == diagnostic)
                step.update(conclusion="skipped", started_at=None, completed_at=None)
                with self.assertRaisesRegex(orchestration.ContractError, "native step did not complete successfully"):
                    validator._job(stage, contract, run, job)

    def test_current_rule_also_rejects_a_baseline_conditional_diagnostic_skip(self):
        for slug in ("ngspice", "nginx"):
            with self.subTest(slug=slug):
                validator, stage, contract, run, job, _, diagnostic = self.layout(slug, conditional_diagnostic=True)
                step = next(step for step in job["steps"] if step["name"] == diagnostic)
                step.update(conclusion="skipped", started_at=None, completed_at=None)
                self.assertNotIn(diagnostic, [step["name"] for step in contract["required_steps"]])
                with self.assertRaisesRegex(orchestration.ContractError, "native step did not complete successfully"):
                    validator._job(stage, contract, run, job)

    def test_mandatory_test_and_final_gate_skips_remain_rejected(self):
        for slug in ("ngspice", "nginx"):
            validator, stage, contract, run, original, _, _ = self.layout(slug)
            for expected in [*contract["required_steps"], contract["final_gate"]]:
                with self.subTest(slug=slug, step=expected["name"]):
                    job = deepcopy(original)
                    step = next(step for step in job["steps"] if step["name"] == expected["name"])
                    step.update(conclusion="skipped", started_at=None, completed_at=None)
                    with self.assertRaises(orchestration.ContractError):
                        validator._job(stage, contract, run, job)


if __name__ == "__main__":
    unittest.main()
