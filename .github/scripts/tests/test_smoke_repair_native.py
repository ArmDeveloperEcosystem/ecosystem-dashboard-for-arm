"""Offline adversarial tests for the native smoke-repair publication gate."""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import smoke_repair_native as native
from orchestration_contract import ContractError, MainAdvanced

REPOSITORY = "example/eco-tom"
BASE, CANDIDATE, TREE = "a" * 40, "b" * 40, "c" * 40
RUN_ID, JOB_ID, WORKFLOW_ID = 1079001, 1079002, 1079003
PATH = ".github/workflows/test-sample.yml"


def when(seconds):
    return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def source_workflow(*, test6=True, job_name=None, explicit_gate=False):
    steps = [{"name": "Install prerequisites", "id": "install", "run": "sudo apt-get install -y build-essential\n"}]
    steps += [{"name": f"Test {index} - Native probe", "id": f"test{index}",
               "continue-on-error": True, "run": "printf 'status=passed\\n' >> \"$GITHUB_OUTPUT\"\n"}
              for index in range(1, 6)]
    if test6:
        steps.append({"name": "Regression applicability", "id": "test6",
                      "run": "printf 'status=skipped\\n' >> \"$GITHUB_OUTPUT\"\n"})
    steps.append({"name": "Calculate test summary", "id": "summary", "if": "always()",
                  "run": "test '${{ steps.test1.outputs.status }}' = passed\n"})
    steps.append({"name": "Create test summary", "run": "printf 'Native observations\\n' >> \"$GITHUB_STEP_SUMMARY\"\n"})
    if explicit_gate:
        steps.append({"name": "Enforce failure status", "if": "always()",
                      "run": 'if [ "${{ steps.summary.outputs.should_fail }}" = 1 ]; then exit 1; fi\n'})
    job = {"runs-on": native.RUNNER, "steps": steps}
    if job_name is not None:
        job["name"] = job_name
    return {"name": "Test Sample on Arm64", "permissions": {"contents": "read"},
            "on": {"workflow_dispatch": None, "workflow_call": None}, "jobs": {"test-sample": job}}


def encode_source(flow):
    return yaml.safe_dump(flow, sort_keys=False).encode()


def digest(source):
    return hashlib.sha256(source).hexdigest()


class Clock:
    def __init__(self, *, advancing=True):
        self.now = 100.0
        self.sleeps = []
        self.advancing = advancing

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if self.advancing:
            self.now += seconds


class GitHubFixture:
    """Serves only hardcoded repository-relative routes; never invokes gh."""

    def __init__(self, flow=None):
        flow = source_workflow() if flow is None else flow
        self.base_source = encode_source(flow)
        candidate_flow = deepcopy(flow)
        next(iter(candidate_flow["jobs"].values()))["steps"][0]["run"] += "export CMAKE_BUILD_PARALLEL_LEVEL=2\n"
        self.candidate_source = encode_source(candidate_flow)
        self.stage = {"schema_version": 1, "repository": REPOSITORY, "repair_id": "1079-1-sample",
                      "base_sha": BASE, "branch": "automation/smoke-repair/1079-1-sample",
                      "candidate_sha": CANDIDATE, "tree_sha": TREE, "workflow_path": PATH,
                      "package_slug": "sample", "proposal_digest": "d" * 64,
                      "source_digest": digest(self.candidate_source)}
        self.contract = native.derive_native_contract(
            self.base_source, repository=REPOSITORY, base_sha=BASE, workflow_path=PATH,
            package_slug="sample", source_digest=self.stage["source_digest"],
        )
        self.workflow = {"id": WORKFLOW_ID, "path": PATH, "name": flow["name"], "state": "active"}
        self.commit = {"sha": CANDIDATE, "tree": {"sha": TREE}, "parents": [{"sha": BASE}]}
        self.main_sha, self.branch_sha = BASE, CANDIDATE
        self.repository = {"full_name": REPOSITORY, "private": False}
        self.ref_overrides = {}
        self.content_overrides = {}
        self.run = {"id": RUN_ID, "run_attempt": 1, "workflow_id": WORKFLOW_ID, "path": PATH,
                    "repository": {"full_name": REPOSITORY}, "head_repository": {"full_name": REPOSITORY},
                    "head_sha": CANDIDATE, "head_branch": self.stage["branch"],
                    "head_commit": {"id": CANDIDATE}, "event": "workflow_dispatch", "name": flow["name"],
                    "status": "completed", "conclusion": "success", "created_at": when(0),
                    "run_started_at": when(5), "updated_at": when(200),
                    "url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}",
                    "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}"}
        names = ["Set up job"] + [step["name"] for step in next(iter(flow["jobs"].values()))["steps"]]
        observations = [{"name": name, "number": index + 1, "status": "completed", "conclusion": "success",
                         "started_at": when(10 + index * 2), "completed_at": when(12 + index * 2)}
                        for index, name in enumerate(names)]
        observations.append({"name": "Complete job", "number": len(names) + 3, "status": "completed",
                             "conclusion": "success", "started_at": when(80), "completed_at": when(80)})
        self.job = {"id": JOB_ID, "run_id": RUN_ID, "run_attempt": 1, "head_sha": CANDIDATE,
                    "head_branch": self.stage["branch"], "name": self.contract["job_name"],
                    "workflow_name": flow["name"], "status": "completed", "conclusion": "success",
                    "started_at": when(10), "completed_at": when(100), "steps": observations,
                    "labels": [native.RUNNER], "runner_id": 44, "runner_name": "Hosted Agent",
                    "runner_group_id": 0, "runner_group_name": "GitHub Actions",
                    "run_url": self.run["url"],
                    "url": f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{JOB_ID}",
                    "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}/job/{JOB_ID}"}
        self.jobs = [self.job]
        self.individual_job = None
        self.post_response = {"workflow_run_id": RUN_ID, "run_url": self.run["url"], "html_url": self.run["html_url"]}
        self.post_accepted = True
        self.dispatched = False
        self.before_runs = []
        self.after_runs = None
        self.visibility_delay = 0
        self.jobs_delay = 0
        self.pending_job_delay = 0
        self.calls = []
        self.on_call = None
        self.page_mutator = None

    @property
    def posts(self):
        return [call for call in self.calls if call[1].get("payload") is not None]

    def source_changed(self, mutate):
        flow = native._yaml_mapping(self.candidate_source, "fixture")
        mutate(flow)
        self.candidate_source = encode_source(flow)
        self.stage["source_digest"] = digest(self.candidate_source)
        self.contract["source_digest"] = self.stage["source_digest"]

    def api(self, endpoint, **options):
        self.calls.append((endpoint, deepcopy(options)))
        if self.on_call:
            self.on_call(endpoint, options)
        if endpoint == "rate_limit":
            return {"resources": {"core": {"limit": 1000, "remaining": 1000, "reset": int(time.time()) + 3600}}}
        if endpoint == f"repos/{REPOSITORY}":
            return deepcopy(self.repository)
        if not endpoint.startswith(f"repos/{REPOSITORY}/"):
            raise AssertionError(f"unexpected or non-repository-relative endpoint: {endpoint}")
        if not 0 < options["timeout"] <= 60 or options.get("pages"):
            raise AssertionError("API calls must be bounded and pagination explicit")
        route = urlsplit(endpoint)
        path = route.path.removeprefix(f"repos/{REPOSITORY}/")
        query = parse_qs(route.query)
        if path.startswith("git/ref/heads/"):
            branch = path.removeprefix("git/ref/heads/")
            if branch not in ("main", self.stage["branch"]):
                raise AssertionError(branch)
            response = {"ref": f"refs/heads/{branch}", "object": {"type": "commit",
                        "sha": self.main_sha if branch == "main" else self.branch_sha}}
            response.update(deepcopy(self.ref_overrides.get(branch, {})))
        elif path == f"git/commits/{CANDIDATE}":
            response = self.commit
        elif path == f"contents/{PATH}":
            sha = query["ref"][0]
            if sha not in (BASE, CANDIDATE):
                raise AssertionError(sha)
            raw = self.base_source if sha == BASE else self.candidate_source
            response = {"type": "file", "path": PATH, "encoding": "base64", "size": len(raw),
                        "content": base64.b64encode(raw).decode(),
                        "sha": hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()}
            response.update(deepcopy(self.content_overrides.get(sha, {})))
        elif path == "actions/workflows/test-sample.yml":
            response = self.workflow
        elif path == "actions/workflows/test-sample.yml/dispatches":
            if options.get("payload") != {"ref": self.stage["branch"]} or query:
                raise AssertionError("dispatch must contain only the automation branch ref")
            self.dispatched = self.post_accepted
            if isinstance(self.post_response, Exception):
                raise self.post_response
            response = self.post_response
        elif path in ("actions/workflows/test-sample.yml/runs", f"actions/runs/{RUN_ID}/attempts/1/jobs"):
            if "event" in query or query.get("per_page") != ["100"]:
                raise AssertionError("inventory must not hide previous runs by event")
            if path.endswith("/runs"):
                if query.get("branch") != [self.stage["branch"]] or query.get("head_sha") != [CANDIDATE]:
                    raise AssertionError("run query is not bound to exact branch/SHA")
                rows = self.before_runs
                if self.dispatched:
                    rows = [self.run] if self.after_runs is None else self.after_runs
                    if self.visibility_delay:
                        self.visibility_delay -= 1
                        rows = []
                key = "workflow_runs"
            else:
                rows, key = self.jobs, "jobs"
                if self.jobs_delay:
                    self.jobs_delay -= 1
                    rows = []
                elif self.pending_job_delay:
                    self.pending_job_delay -= 1
                    rows = [dict(self.job, status="in_progress", conclusion=None)]
            start = (int(query["page"][0]) - 1) * 100
            response = {"total_count": len(rows), key: deepcopy(rows[start:start + 100])}
            if self.page_mutator:
                self.page_mutator(path, int(query["page"][0]), response)
        elif path.startswith("actions/runs/") and path.count("/") == 2:
            if path != f"actions/runs/{RUN_ID}":
                raise AssertionError("native followed an unauthenticated run ID")
            response = self.run
        elif path == f"actions/jobs/{JOB_ID}":
            response = self.individual_job if self.individual_job is not None else self.job
        else:
            raise AssertionError(f"unexpected API route: {endpoint}")
        return deepcopy(response)


class NativeValidationTests(unittest.TestCase):
    def setUp(self):
        self.api = GitHubFixture()
        self.clock = Clock()

    def validator(self, api=None, **options):
        return native.NativeValidation(api or self.api, clock=self.clock, sleep=self.clock.sleep,
                                       **{"max_polls": 5, **options})

    def dispatch(self, api=None, **options):
        api = api or self.api
        return self.validator(api, **options).dispatch_and_wait(api.stage, api.contract)

    def assert_blocked(self, api, *, before_post=False):
        with self.assertRaises(ContractError):
            self.dispatch(api)
        self.assertLessEqual(len(api.posts), 1)
        if before_post:
            self.assertEqual(api.posts, [])

    def test_valid_dispatch_and_read_only_publisher_verification(self):
        receipt = self.dispatch()
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["stage"], self.api.stage)
        self.assertEqual(receipt["run"]["id"], RUN_ID)
        self.assertEqual(receipt["job"]["id"], JOB_ID)
        self.assertEqual(receipt["steps"], self.api.job["steps"])
        self.assertEqual(receipt["contract_digest"], native._digest(self.api.contract))
        self.assertNotIn("tests_passed", json.dumps(receipt))
        self.assertNotIn("tests_skipped", json.dumps(receipt))
        self.assertEqual(len(self.api.posts), 1)
        self.assertEqual(self.api.posts[0][1]["payload"], {"ref": self.api.stage["branch"]})
        before = len(self.api.calls)
        observed = native.verify_native_receipt(self.api.stage, receipt, self.api.contract, api=self.api,
                                               clock=self.clock, sleep=self.clock.sleep)
        self.assertEqual(observed, receipt)
        self.assertEqual(len(self.api.posts), 1)
        reads = [call[0] for call in self.api.calls[before:]]
        self.assertIn(f"repos/{REPOSITORY}/actions/jobs/{JOB_ID}", reads)
        self.assertTrue(any(f"/attempts/1/jobs?" in endpoint for endpoint in reads))
        self.assertTrue(any(f"/contents/{PATH}?ref={CANDIDATE}" in endpoint for endpoint in reads))

    def test_receipt_has_no_shared_mutable_references(self):
        receipt = self.dispatch()
        receipt["stage"]["candidate_sha"] = "f" * 40
        receipt["steps"][0]["name"] = "changed"
        self.assertEqual(self.api.stage["candidate_sha"], CANDIDATE)
        self.assertEqual(self.api.job["steps"][0]["name"], "Set up job")

    def test_empty_and_id_only_dispatch_responses(self):
        for response in (None, {"workflow_run_id": RUN_ID}):
            with self.subTest(response=response):
                api = GitHubFixture()
                api.post_response = response
                self.assertEqual(self.dispatch(api)["status"], "passed")
                self.assertEqual(len(api.posts), 1)

    def test_ambiguous_post_reconciles_without_redispatch(self):
        for error in (ContractError("transport uncertain"), TimeoutError("transport timeout")):
            with self.subTest(error=type(error)):
                api = GitHubFixture()
                api.post_response = error
                api.visibility_delay = 2
                self.assertEqual(self.dispatch(api)["run"]["id"], RUN_ID)
                self.assertEqual(len(api.posts), 1)

    def test_ambiguous_post_without_run_is_not_passed_or_redispatched(self):
        self.api.post_response = ContractError("lost response")
        self.api.post_accepted = False
        validator = self.validator()
        with self.assertRaisesRegex(ContractError, "not passed"):
            validator.dispatch_and_wait(self.api.stage, self.api.contract)
        with self.assertRaisesRegex(ContractError, "already attempted"):
            validator.dispatch_and_wait(self.api.stage, self.api.contract)
        self.assertEqual(len(self.api.posts), 1)

    def test_dispatch_response_fields_cannot_control_endpoints(self):
        responses = [False, [], {}, {"id": RUN_ID}, {"workflow_run_id": RUN_ID, "extra": "value"}]
        responses += [{"workflow_run_id": value} for value in (True, 0, -1, "1079001", 1.0, None, 2**80)]
        responses += [{"workflow_run_id": RUN_ID, key: url} for key in ("run_url", "html_url") for url in
                      ("https://evil.invalid/run", "repos/other/project/actions/runs/1", self.api.run["html_url"] + "?x=y")]
        for response in responses:
            with self.subTest(response=response):
                api = GitHubFixture()
                api.post_response = response
                self.assert_blocked(api)

    def test_dispatch_run_id_must_match_exact_registration(self):
        self.api.after_runs = [dict(self.api.run, id=RUN_ID + 1)]
        self.assert_blocked(self.api)

    def test_ambiguous_registration_and_later_duplicates_fail_closed(self):
        for legacy in (True, False):
            with self.subTest(legacy=legacy):
                api = GitHubFixture()
                if legacy:
                    api.post_response = None
                api.after_runs = [api.run, dict(api.run, id=RUN_ID + 1)]
                self.assert_blocked(api)
        api = GitHubFixture()
        receipt = self.dispatch(api)
        api.after_runs = [api.run, dict(api.run, id=RUN_ID + 1)]
        with self.assertRaises(ContractError):
            self.validator(api).verify(api.stage, receipt, api.contract)
        self.assertEqual(len(api.posts), 1)

    def test_prior_runs_of_any_status_event_or_attempt_block_post(self):
        for event in ("workflow_dispatch", "push", "pull_request"):
            for attempt in (1, 2):
                for status in ("queued", "completed"):
                    with self.subTest(event=event, attempt=attempt, status=status):
                        api = GitHubFixture()
                        api.before_runs = [dict(api.run, event=event, run_attempt=attempt, status=status)]
                        self.assert_blocked(api, before_post=True)

    def test_paginated_prior_run_inventory_never_dispatches(self):
        self.api.before_runs = [dict(self.api.run, id=RUN_ID + index) for index in range(101)]
        self.assert_blocked(self.api, before_post=True)
        self.assertTrue(any("/runs?" in endpoint and "page=2" in endpoint
                            for endpoint, _ in self.api.calls))

    def test_empty_inventory_through_dispatch_uses_nine_reserved_requests(self):
        self.dispatch()
        endpoints = [endpoint for endpoint, _ in self.api.calls]
        inventory = next(index for index, endpoint in enumerate(endpoints) if "/runs?" in endpoint)
        posted = next(index for index, endpoint in enumerate(endpoints) if endpoint.endswith("/dispatches"))
        final_reads = endpoints[inventory - 2:posted + 1]
        self.assertEqual(len(final_reads), 9)
        self.assertNotIn("rate_limit", final_reads)
        self.assertEqual(self.clock.sleeps, [])

    def test_legacy_response_with_wrong_run_is_never_accepted(self):
        for field, value in (("head_sha", BASE), ("head_branch", "main"), ("event", "push"),
                             ("path", ".github/workflows/test-other.yml"), ("run_attempt", 2)):
            with self.subTest(field=field):
                api = GitHubFixture()
                api.post_response = None
                api.run[field] = value
                self.assert_blocked(api)

    def test_exact_run_identity_is_strict(self):
        mutations = {
            "id": (True, RUN_ID + 1, str(RUN_ID), -1), "workflow_id": (True, WORKFLOW_ID + 1, None),
            "run_attempt": (True, 1.0, "1", 0, 2), "head_sha": (BASE, "b" * 39, "B" * 40, None),
            "head_branch": ("main", "refs/heads/" + self.api.stage["branch"], "automation/smoke-repair/1079-2-sample"),
            "path": ("test-sample.yml", PATH + "@refs/heads/main", ".github/workflows/test-other.yml"),
            "event": ("push", "workflow_call", "pull_request", None), "name": ("Test Other", None),
            "repository": ({"full_name": "evil/fork"}, {}, None, []),
            "head_repository": ({"full_name": "evil/fork"}, {}, None),
            "head_commit": ({"id": BASE}, {}, None),
            "url": ("https://evil.invalid/run", self.api.run["url"] + "0"),
            "html_url": ("https://evil.invalid/run", self.api.run["html_url"] + "0"),
        }
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    api = GitHubFixture()
                    api.run[field] = value
                    self.assert_blocked(api)

    def test_run_failures_and_invalid_statuses_are_not_passes(self):
        for conclusion in ("failure", "cancelled", "timed_out", "skipped", "neutral", "action_required", None, True, []):
            with self.subTest(conclusion=conclusion):
                api = GitHubFixture()
                api.run["conclusion"] = conclusion
                self.assert_blocked(api)
        for status in ("queued", "unknown", None, True, []):
            with self.subTest(status=status):
                api = GitHubFixture()
                api.run["status"] = status
                self.assert_blocked(api)

    def test_run_timestamps_and_duration_are_authenticated(self):
        mutations = [(field, value) for field in ("created_at", "run_started_at", "updated_at")
                     for value in (None, "", "2026-01-01", "2026-01-01T00:00:00", "2026-99-01T00:00:00Z", 1)]
        mutations += [("created_at", when(300)), ("run_started_at", when(300)),
                      ("updated_at", when(-1)), ("updated_at", when(native.MAX_SECONDS + 1))]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                api = GitHubFixture()
                api.run[field] = value
                self.assert_blocked(api)

    def test_completed_run_is_rechecked_after_jobs_to_detect_rerun(self):
        def rerun(endpoint, options):
            if endpoint.endswith(f"actions/jobs/{JOB_ID}"):
                self.api.run["run_attempt"] = 2
        self.api.on_call = rerun
        self.assert_blocked(self.api)

    def test_standalone_job_binding_and_runner_are_strict(self):
        mutations = {
            "id": (True, 0, "1079002"), "run_id": (True, RUN_ID + 1, "1079001"),
            "run_attempt": (True, 1.0, "1", 0, 2), "head_sha": (BASE, None),
            "head_branch": ("main", None), "name": ("batch / test-sample", "test-other", None),
            "workflow_name": ("other", None), "run_url": ("https://evil.invalid/run", None),
            "url": ("https://evil.invalid/job", None), "html_url": ("https://evil.invalid/job", None),
            "labels": (["ubuntu-latest"], ["ubuntu-24.04"], ["self-hosted", native.RUNNER],
                       [native.RUNNER, native.RUNNER], [], native.RUNNER, None),
            "runner_id": (True, "44", 0, None), "runner_name": (None, "", "${{ arbitrary }}"),
            "runner_group_id": (True, "0", 1, -1, None),
            "runner_group_name": (None, "", "Default", "github actions"),
            "status": ("skipped", "unknown", True), "conclusion": ("failure", "skipped", "cancelled", "neutral", None),
        }
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    api = GitHubFixture()
                    api.job[field] = value
                    self.assert_blocked(api)

    def test_self_hosted_runner_with_matching_requested_label_is_not_hosted_proof(self):
        self.api.job.update(runner_name="self-hosted-builder", runner_group_id=7,
                            runner_group_name="Default")
        self.assert_blocked(self.api)

    def test_free_hosted_validation_requires_live_public_repository(self):
        for repository in ({"full_name": REPOSITORY, "private": True},
                           {"full_name": REPOSITORY}, {"full_name": REPOSITORY, "private": 0},
                           {"full_name": "other/repo", "private": False}):
            with self.subTest(repository=repository):
                api = GitHubFixture()
                api.repository = repository
                self.assert_blocked(api, before_post=True)

    def test_repository_becoming_private_invalidates_native_receipt(self):
        receipt = self.dispatch()
        self.api.repository["private"] = True
        with self.assertRaises(ContractError):
            self.validator().verify(self.api.stage, receipt, self.api.contract)

    def test_missing_nonmandatory_workflow_step_is_incomplete_evidence(self):
        for name in ("Install prerequisites", "Create test summary"):
            with self.subTest(name=name):
                api = GitHubFixture()
                step = next(step for step in api.job["steps"] if step["name"] == name)
                api.job["steps"].remove(step)
                self.assert_blocked(api)

    def test_job_inventory_must_contain_exactly_one_expected_job(self):
        for kind in ("empty", "extra", "duplicate", "null", "scalar"):
            with self.subTest(kind=kind):
                api = GitHubFixture()
                if kind == "empty":
                    api.jobs = []
                elif kind == "extra":
                    api.jobs.append(dict(api.job, id=JOB_ID + 1, name="summary"))
                elif kind == "duplicate":
                    api.jobs.append(deepcopy(api.job))
                elif kind == "null":
                    api.jobs = [None]
                else:
                    api.jobs = ["not a job"]
                self.assert_blocked(api)

    def test_individual_job_must_match_inventory(self):
        for field, value in (("id", JOB_ID + 1), ("id", True), ("run_id", RUN_ID + 1),
                             ("started_at", when(9)), ("runner_id", 45), ("steps", [])):
            with self.subTest(field=field, value=value):
                api = GitHubFixture()
                api.individual_job = dict(api.job, **{field: value})
                self.assert_blocked(api)

    def test_all_mandatory_steps_and_gate_must_succeed(self):
        targets = self.api.contract["mandatory_steps"] + [self.api.contract["gate_step"]]
        for name in targets:
            for defect in ("missing", "skipped", "failure", "pending", "number", "duplicate"):
                with self.subTest(name=name, defect=defect):
                    api = GitHubFixture()
                    step = next(step for step in api.job["steps"] if step["name"] == name)
                    if defect == "missing":
                        api.job["steps"].remove(step)
                    elif defect == "duplicate":
                        api.job["steps"].append(deepcopy(step))
                    elif defect == "number":
                        step["number"] += 100
                    elif defect == "pending":
                        step.update(status="in_progress", conclusion=None)
                    else:
                        step["conclusion"] = defect
                    self.assert_blocked(api)

    def test_step_shapes_numbers_names_and_timestamps_are_strict(self):
        mutations = {
            "number": (True, 0, -1, 2.0, "2", None, 1001),
            "name": (None, "", "Test\nInjected", "${{ inputs.name }}"),
            "started_at": (None, when(0), when(190), "invalid"),
            "completed_at": (None, when(0), when(300), "invalid"),
            "status": ("queued", None), "conclusion": ("skipped", "failure", None),
        }
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    api = GitHubFixture()
                    api.job["steps"][2][field] = value
                    self.assert_blocked(api)
        for steps in (None, [], [None], "not steps", [{}] * 201):
            with self.subTest(steps=type(steps)):
                api = GitHubFixture()
                api.job["steps"] = steps
                self.assert_blocked(api)

    def test_step_order_and_overlap_cannot_be_hidden_by_names(self):
        for defect in ("number_order", "time_order", "duplicate_name", "reversed"):
            with self.subTest(defect=defect):
                api = GitHubFixture()
                steps = api.job["steps"]
                if defect == "number_order":
                    steps[2], steps[3] = steps[3], steps[2]
                elif defect == "time_order":
                    steps[3]["started_at"] = steps[2]["started_at"]
                elif defect == "duplicate_name":
                    steps[3]["name"] = steps[2]["name"]
                else:
                    steps[2]["completed_at"] = when(1)
                self.assert_blocked(api)

    def test_rfc3339_step_offsets_compare_as_instants(self):
        for step in self.api.job["steps"]:
            for key in ("started_at", "completed_at"):
                step[key] = datetime.fromisoformat(step[key].replace("Z", "+00:00")).astimezone(
                    timezone(timedelta(hours=-8))).isoformat()
        self.assertEqual(self.dispatch()["status"], "passed")

    def test_job_timestamps_must_be_within_exact_run(self):
        for field, value in (("started_at", when(0)), ("started_at", when(101)),
                             ("completed_at", when(201)), ("completed_at", when(9)),
                             ("started_at", None), ("completed_at", "not-time")):
            with self.subTest(field=field, value=value):
                api = GitHubFixture()
                api.job[field] = value
                self.assert_blocked(api)

    def test_delayed_registration_run_and_job_inventory_can_complete(self):
        self.api.visibility_delay = 1
        self.api.jobs_delay = 1
        self.api.pending_job_delay = 1
        self.assertEqual(self.dispatch()["status"], "passed")
        self.assertEqual(len(self.clock.sleeps), 3)
        self.assertEqual(len(self.api.posts), 1)
        api = GitHubFixture()
        api.run.update(status="queued", conclusion=None, run_started_at=None)
        def complete(seconds):
            self.clock.sleep(seconds)
            api.run.update(status="completed", conclusion="success", run_started_at=when(5))
        validator = native.NativeValidation(api, clock=self.clock, sleep=complete, max_polls=3)
        self.assertEqual(validator.dispatch_and_wait(api.stage, api.contract)["status"], "passed")

    def test_frozen_clock_still_has_finite_polling(self):
        self.clock.advancing = False
        self.api.run.update(status="in_progress", conclusion=None)
        with self.assertRaisesRegex(ContractError, "polling bound"):
            self.dispatch(max_polls=3)
        self.assertEqual(len(self.clock.sleeps), 2)
        self.assertEqual(len(self.api.posts), 1)
        self.assertLess(len(self.api.calls), 100)

    def test_default_polling_leaves_api_capacity_for_two_workers(self):
        self.api.run.update(status="in_progress", conclusion=None)
        validator = native.NativeValidation(self.api, clock=self.clock, sleep=self.clock.sleep)
        self.assertEqual(validator.poll_interval, 90)
        with self.assertRaisesRegex(ContractError, "timed out"):
            validator.dispatch_and_wait(self.api.stage, self.api.contract)
        self.assertEqual(sum(self.clock.sleeps), native.MAX_SECONDS)
        # Two long-running workers must leave room below the shared 1000/h limit.
        self.assertLess(len(self.api.calls) * 2, 650)
        self.assertEqual(len(self.api.posts), 1)

    def test_deadline_stops_sleep_and_never_cancels_unknown_runs(self):
        self.api.run.update(status="queued", conclusion=None)
        with self.assertRaisesRegex(ContractError, "timed out"):
            self.dispatch(timeout_seconds=1, poll_interval=10)
        self.assertAlmostEqual(sum(self.clock.sleeps), 1)
        self.assertTrue(all(0 < seconds <= 1 for seconds in self.clock.sleeps))
        self.assertEqual(len(self.api.posts), 1)
        self.assertFalse(any("/cancel" in endpoint for endpoint, _ in self.api.calls))

    def test_expensive_api_call_cannot_finish_after_deadline(self):
        def delay(endpoint, options):
            if endpoint.endswith(f"actions/jobs/{JOB_ID}"):
                self.clock.now += 20
        self.api.on_call = delay
        with self.assertRaisesRegex(ContractError, "timed out"):
            self.dispatch(timeout_seconds=10)

    def test_timeout_configuration_is_bounded_and_strict(self):
        validator = self.validator(timeout_seconds=100000, deadline=self.clock() + 100000)
        self.assertEqual(validator.deadline, self.clock() + native.MAX_SECONDS)
        validator = self.validator(deadline=self.clock() + 5)
        self.assertEqual(validator.deadline, self.clock() + 5)
        for key in ("timeout_seconds", "poll_interval", "max_polls", "max_pages"):
            for value in (True, 0, -1, "10", float("nan"), float("inf")):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ContractError):
                        self.validator(**{key: value})
        for value in (True, "10", float("nan"), float("inf"), self.clock()):
            with self.subTest(deadline=value):
                with self.assertRaises(ContractError):
                    self.validator(deadline=value)
        for key, value in (("max_polls", native.MAX_POLLS + 1), ("max_pages", native.MAX_PAGES + 1)):
            with self.assertRaises(ContractError):
                self.validator(**{key: value})

    def test_nonfinite_or_backward_clock_cannot_produce_unbounded_polling(self):
        with self.assertRaises(ContractError):
            native.NativeValidation(self.api, clock=lambda: float("nan"))
        self.api.after_runs = []
        def backwards(seconds):
            self.clock.now -= 100
        validator = native.NativeValidation(self.api, clock=self.clock, sleep=backwards, max_polls=2)
        with self.assertRaises(ContractError):
            validator.dispatch_and_wait(self.api.stage, self.api.contract)
        self.assertLess(len(self.api.calls), 80)

    def test_missing_status_or_conclusion_is_not_a_pending_state(self):
        for entity in ("run", "job"):
            for field in ("status", "conclusion"):
                with self.subTest(entity=entity, field=field):
                    api = GitHubFixture()
                    payload = getattr(api, entity)
                    payload.update(status="queued", conclusion=None)
                    del payload[field]
                    self.assert_blocked(api)

    def test_main_and_branch_are_checked_before_post(self):
        for field in ("main_sha", "branch_sha"):
            with self.subTest(field=field):
                api = GitHubFixture()
                setattr(api, field, "f" * 40)
                with self.assertRaises(MainAdvanced):
                    self.dispatch(api)
                self.assertEqual(api.posts, [])
        self.api.page_mutator = lambda path, page, payload: setattr(self.api, "main_sha", "f" * 40)
        self.assert_blocked(self.api, before_post=True)

    def test_main_and_branch_are_checked_during_wait_and_before_return(self):
        for field in ("main_sha", "branch_sha"):
            for at in ("sleep", "job"):
                with self.subTest(field=field, at=at):
                    api = GitHubFixture()
                    def advance(seconds):
                        self.clock.sleep(seconds)
                        setattr(api, field, "f" * 40)
                    if at == "sleep":
                        api.after_runs = []
                        validator = native.NativeValidation(api, clock=self.clock, sleep=advance, max_polls=3)
                    else:
                        def mutate(endpoint, options):
                            if endpoint.endswith(f"actions/jobs/{JOB_ID}"):
                                setattr(api, field, "f" * 40)
                        api.on_call = mutate
                        validator = self.validator(api)
                    with self.assertRaises(MainAdvanced):
                        validator.dispatch_and_wait(api.stage, api.contract)
                    self.assertEqual(len(api.posts), 1)

    def test_ref_objects_are_not_accepted_by_sha_alone(self):
        for branch in ("main", self.api.stage["branch"]):
            for override in ({"ref": "refs/tags/main"}, {"object": {"type": "tag", "sha": BASE}},
                             {"object": None}, {"object": {"type": "commit", "sha": True}}):
                with self.subTest(branch=branch, override=override):
                    api = GitHubFixture()
                    api.ref_overrides[branch] = override
                    self.assert_blocked(api, before_post=True)

    def test_pagination_is_complete_bounded_and_unique(self):
        for total in (0, 1, 100, 101):
            with self.subTest(total=total):
                api = GitHubFixture()
                api.before_runs = [dict(api.run, id=RUN_ID + index) for index in range(total)]
                result = self.validator(api)._runs(api.stage)
                self.assertEqual(len(result), total)
                pages = [endpoint for endpoint, _ in api.calls if "/runs?" in endpoint]
                self.assertEqual(len(pages), max(1, (total + 99) // 100))
        mutations = [lambda page: page.update(total_count=True), lambda page: page.update(total_count="0"),
                     lambda page: page.update(total_count=-1), lambda page: page.update(total_count=1001),
                     lambda page: page.update(total_count=1), lambda page: page.pop("total_count"),
                     lambda page: page.update(workflow_runs=None), lambda page: page.update(workflow_runs=[{}])]
        for mutation in mutations:
            api = GitHubFixture()
            api.page_mutator = lambda path, number, page: mutation(page)
            self.assert_blocked(api, before_post=True)
        for defect in ("count_change", "duplicate", "truncated"):
            with self.subTest(defect=defect):
                api = GitHubFixture()
                api.before_runs = [dict(api.run, id=RUN_ID + index) for index in range(101)]
                def corrupt(path, number, page):
                    if number == 2:
                        if defect == "count_change":
                            page["total_count"] = 102
                        elif defect == "duplicate":
                            page["workflow_runs"][0]["id"] = RUN_ID
                        else:
                            page["workflow_runs"] = []
                api.page_mutator = corrupt
                self.assert_blocked(api, before_post=True)

    def test_jobs_pagination_cannot_hide_extra_or_missing_jobs(self):
        for total in (0, 2, True, "1", None):
            with self.subTest(total=total):
                api = GitHubFixture()
                def mutate(path, number, page):
                    if path.endswith("/jobs"):
                        page["total_count"] = total
                api.page_mutator = mutate
                self.assert_blocked(api)

    def test_stage_schema_ref_and_digest_validation(self):
        mutations = {
            "schema_version": (True, 1.0, 2), "repository": ("https://evil.invalid", "../repo", "org/repo?x", None),
            "base_sha": (True, "a" * 39, "A" * 40), "candidate_sha": (BASE, "b" * 39, None),
            "tree_sha": ("c" * 39, None), "repair_id": ("0-1-sample", "1079-0-sample", "01079-1-sample", "1079-1-other"),
            "branch": ("main", "refs/heads/automation/smoke-repair/1079-1-sample", "automation/smoke-repair/1079-2-sample"),
            "package_slug": ("sample/other", "sample?x", "", None),
            "workflow_path": ("https://evil.invalid", "../test-sample.yml", ".github/workflows/test-sample.yml?ref=x",
                              ".github/workflows/test-all-packages-batch1.yml"),
            "source_digest": (True, "f" * 63, "F" * 64), "proposal_digest": ("x" * 64, None),
        }
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    api = GitHubFixture()
                    api.stage[field] = value
                    self.assert_blocked(api, before_post=True)
                    self.assertEqual(api.calls, [])
        for field in list(self.api.stage):
            stage = dict(self.api.stage)
            del stage[field]
            with self.assertRaises(ContractError):
                native.validate_stage(stage)
        for stage in (None, [], dict(self.api.stage, unexpected=True)):
            with self.assertRaises(ContractError):
                native.validate_stage(stage)

    def test_candidate_commit_tree_and_parent_must_match_stage(self):
        for field, value in (("sha", BASE), ("tree", {"sha": BASE}), ("tree", None), ("parents", []),
                             ("parents", [{"sha": CANDIDATE}]), ("parents", [{"sha": BASE}, {"sha": TREE}]),
                             ("parents", [None])):
            with self.subTest(field=field, value=value):
                api = GitHubFixture()
                api.commit[field] = value
                self.assert_blocked(api, before_post=True)

    def test_minimal_contract_fields_are_derived_not_trusted(self):
        self.assertEqual(set(self.api.contract), {"called_job", "job_name", "mandatory_steps", "gate_step", "workflow_path", "source_digest"})
        mutations = {"called_job": ("other", True), "job_name": ("other", True),
                     "mandatory_steps": ([], True, self.api.contract["mandatory_steps"][:-1],
                                         self.api.contract["mandatory_steps"] * 2),
                     "gate_step": (None, "Test 1 - Native probe"), "workflow_path": ("https://evil.invalid",),
                     "source_digest": ("e" * 64,)}
        for field, values in mutations.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    api = GitHubFixture()
                    api.contract[field] = value
                    self.assert_blocked(api, before_post=True)
        for field in self.api.contract:
            api = GitHubFixture()
            del api.contract[field]
            self.assert_blocked(api, before_post=True)

    def test_extra_contract_metadata_is_bound_and_cannot_override_requirements(self):
        self.api.contract["policy_version"] = "reviewed-v1"
        receipt = self.dispatch()
        self.api.contract["policy_version"] = "other-policy"
        with self.assertRaises(ContractError):
            self.validator().verify(self.api.stage, receipt, self.api.contract)
        for extra in ({"runner_labels": ["self-hosted"]}, {"schema_version": True}, {"permissions": {"contents": "write"}}):
            api = GitHubFixture()
            api.contract.update(extra)
            self.assert_blocked(api, before_post=True)

    def test_workflow_api_identity_must_match_base(self):
        for field, value in (("id", True), ("id", "12"), ("path", ".github/workflows/test-other.yml"),
                             ("name", "Other"), ("state", "disabled_manually")):
            with self.subTest(field=field, value=value):
                api = GitHubFixture()
                api.workflow[field] = value
                self.assert_blocked(api, before_post=True)

    def test_source_bytes_must_match_blob_identity_size_and_stage_digest(self):
        overrides = ({"encoding": "none"}, {"content": "not base64!"}, {"content": "AAAA"}, {"content": None},
                     {"type": "symlink"}, {"path": ".github/workflows/test-other.yml"}, {"size": True},
                     {"size": native.MAX_WORKFLOW_BYTES + 1}, {"size": 1}, {"sha": "e" * 40})
        for sha in (BASE, CANDIDATE):
            for override in overrides:
                with self.subTest(sha=sha[0], override=override):
                    api = GitHubFixture()
                    api.content_overrides[sha] = override
                    self.assert_blocked(api, before_post=True)
        self.api.candidate_source += b"\n# not bound to stage\n"
        self.assert_blocked(self.api, before_post=True)

    def test_candidate_metadata_and_final_gate_are_frozen(self):
        def job(flow):
            return flow["jobs"]["test-sample"]
        mutations = [lambda flow: flow.update(name="Changed workflow"),
                     lambda flow: job(flow).update(name="Changed standalone name"),
                     lambda flow: job(flow)["steps"][1].update(name="Renamed test"),
                     lambda flow: job(flow)["steps"][1].update(**{"continue-on-error": False}),
                     lambda flow: job(flow)["steps"][1].update(**{"if": "false"}),
                     lambda flow: job(flow)["steps"][-2].update(run="exit 0\n"),
                     lambda flow: job(flow)["steps"][-1].update(run="exit 0\n"),
                     lambda flow: flow.update(env={"UNTRUSTED": "changed"})]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                api = GitHubFixture()
                api.source_changed(mutation)
                self.assert_blocked(api, before_post=True)

    def test_verification_rejects_any_changed_receipt_observation(self):
        receipt = self.dispatch()
        mutations = [lambda value: value.update(status="success"), lambda value: value.update(schema_version=True),
                     lambda value: value.update(contract_digest="e" * 64),
                     lambda value: value.update(tests_passed=6),
                     lambda value: value["run"].update(id=True), lambda value: value["run"].update(id=RUN_ID + 1),
                     lambda value: value["run"].update(run_attempt=True), lambda value: value["run"].update(head_sha=BASE),
                     lambda value: value["job"].update(id=JOB_ID + 1), lambda value: value["job"].update(run_attempt=2),
                     lambda value: value["steps"][2].update(conclusion="skipped"),
                     lambda value: value["steps"].pop(), lambda value: value["stage"].update(source_digest="e" * 64)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed = deepcopy(receipt)
                mutate(changed)
                with self.assertRaises(ContractError):
                    self.validator().verify(self.api.stage, changed, self.api.contract)
        self.assertEqual(len(self.api.posts), 1)

    def test_receipt_is_not_transferable_between_stages(self):
        receipt = self.dispatch()
        for field, value in (("base_sha", "f" * 40), ("candidate_sha", "f" * 40), ("tree_sha", "f" * 40),
                             ("proposal_digest", "e" * 64), ("source_digest", "e" * 64)):
            with self.subTest(field=field):
                stage = dict(self.api.stage, **{field: value})
                with self.assertRaises(ContractError):
                    self.validator().verify(stage, receipt, self.api.contract)

    def test_verification_requires_current_live_evidence(self):
        for defect in ("missing_run", "missing_job", "rerun", "main_advance", "branch_advance", "source_change", "step_failure"):
            with self.subTest(defect=defect):
                api = GitHubFixture()
                receipt = self.dispatch(api)
                if defect == "missing_run":
                    api.after_runs = []
                elif defect == "missing_job":
                    api.jobs = []
                elif defect == "rerun":
                    api.run["run_attempt"] = 2
                elif defect == "main_advance":
                    api.main_sha = "f" * 40
                elif defect == "branch_advance":
                    api.branch_sha = "f" * 40
                elif defect == "source_change":
                    api.candidate_source += b"# altered\n"
                else:
                    api.job["steps"][2]["conclusion"] = "failure"
                with self.assertRaises(ContractError):
                    self.validator(api).verify(api.stage, receipt, api.contract)
                self.assertEqual(len(api.posts), 1)


class NativeRateLimitTests(unittest.TestCase):
    EPOCH = 2_000_000_000

    def setUp(self):
        self.clock = Clock()
        self.clock.now = 0.0
        self.core = {"limit": 1000, "remaining": 1000, "reset": self.EPOCH + 100}
        self.calls = []

    def api(self, endpoint, **options):
        self.calls.append(endpoint)
        self.assertGreater(options["timeout"], 0)
        self.assertLessEqual(options["timeout"], 60)
        self.assertNotIn("payload", options)
        self.assertEqual(endpoint, "rate_limit")
        return {"resources": {"core": deepcopy(self.core)}}

    def validator(self, api=None, **options):
        from types import SimpleNamespace
        return native.NativeValidation(api or SimpleNamespace(api=self.api),
            clock=self.clock, sleep=self.clock.sleep,
            wall_clock=lambda: self.EPOCH + self.clock.now, **options)

    def test_low_budget_waits_and_rechecks_before_granting_credit(self):
        self.core["remaining"] = 0
        validator = self.validator()
        def sleep(seconds):
            self.clock.sleep(seconds)
            self.core.update(remaining=1000, reset=self.EPOCH + int(self.clock.now) + 3600)
        validator.sleep = sleep
        validator._rate_budget(minimum_requests=3)
        self.assertEqual(self.clock.sleeps, [101])
        self.assertEqual(self.calls, ["rate_limit", "rate_limit"])
        self.assertEqual(validator._rate_credit, native.RATE_CHECK_REQUESTS)

    def test_invalid_or_unrecoverable_budget_never_sleeps_or_grants_credit(self):
        for changes in ({"remaining": True}, {"remaining": -1}, {"remaining": 1001},
                        {"limit": 0}, {"limit": True}, {"reset": True},
                        {"reset": self.EPOCH + 7201},
                        {"remaining": 0, "reset": self.EPOCH - 2},
                        {"remaining": 0, "reset": self.EPOCH + 3600}):
            with self.subTest(changes=changes):
                self.setUp()
                self.core.update(changes)
                validator = self.validator()
                with self.assertRaises(ContractError):
                    validator._rate_budget()
                self.assertEqual(self.clock.sleeps, [])
                self.assertEqual(validator._rate_credit, 0)

    def test_reset_does_not_imply_a_restored_shared_quota(self):
        self.core["remaining"] = 0
        validator = self.validator()
        def sleep(seconds):
            self.clock.sleep(seconds)
            self.core["reset"] = self.EPOCH + int(self.clock.now) + 10
        validator.sleep = sleep
        with self.assertRaisesRegex(ContractError, "bounded waits"):
            validator._rate_budget()
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(validator._rate_credit, 0)

    def test_main_advance_during_quota_wait_prevents_dispatch(self):
        fixture = GitHubFixture()
        original_api = fixture.api
        validator = self.validator(fixture)
        blocked = False
        waited = False
        def api(endpoint, **options):
            nonlocal blocked
            if endpoint == "rate_limit":
                return {"resources": {"core": {"limit": 1000, "remaining": 0 if blocked and not waited else 1000,
                    "reset": self.EPOCH + int(self.clock.now) + 10}}}
            result = original_api(endpoint, **options)
            if "/runs?" in endpoint:
                blocked = True
                validator._rate_credit = 0
            return result
        def sleep(seconds):
            nonlocal waited
            waited = True
            self.clock.sleep(seconds)
            fixture.main_sha = "d" * 40
        fixture.api = api
        validator.sleep = sleep
        with self.assertRaises(ContractError):
            validator.dispatch_and_wait(fixture.stage, fixture.contract)
        self.assertTrue(waited)
        self.assertEqual(fixture.posts, [])

    def test_prior_run_appearing_during_predispatch_quota_wait_prevents_post(self):
        fixture = GitHubFixture()
        original_api = fixture.api
        validator = self.validator(fixture)
        prepared = validator._prepare
        waiting = False
        waited = False

        def prepare(*args):
            nonlocal waiting
            result = prepared(*args)
            waiting = True
            # Allow the initial inventory, then force the pre-POST quota wait.
            validator._rate_credit = 5
            return result

        def api(endpoint, **options):
            if endpoint == "rate_limit":
                return {"resources": {"core": {"limit": 1000,
                    "remaining": 0 if waiting and not waited else 1000,
                    "reset": self.EPOCH + int(self.clock.now) + 10}}}
            return original_api(endpoint, **options)

        def sleep(seconds):
            nonlocal waited
            waited = True
            self.clock.sleep(seconds)
            fixture.before_runs = [deepcopy(fixture.run)]

        fixture.api = api
        validator._prepare = prepare
        validator.sleep = sleep
        with self.assertRaisesRegex(ContractError, "prior native runs"):
            validator.dispatch_and_wait(fixture.stage, fixture.contract)
        self.assertTrue(waited)
        self.assertEqual(fixture.posts, [])

    def test_two_workers_and_ten_repair_profiles_share_the_observed_allowance(self):
        from types import SimpleNamespace
        windows = [790]
        available = 210
        probes = 0
        def api(endpoint, **options):
            nonlocal available, probes
            if endpoint == "rate_limit":
                probes += 1
                return {"resources": {"core": {"limit": 1000, "remaining": available,
                    "reset": self.EPOCH + (len(windows) * 3600)}}}
            self.assertEqual(endpoint, "repos/example/eco-tom/read-only-evidence")
            self.assertGreater(available, 0, "a primary request must not overrun shared quota")
            available -= 1
            windows[-1] += 1
            return {}
        service = SimpleNamespace(api=api)
        def sleep(seconds):
            nonlocal available
            self.clock.sleep(seconds)
            available = 1000
            windows.append(0)
        # Both workers may observe the same remaining quota before using credits.
        first, second = self.validator(service), self.validator(service)
        first._rate_budget()
        second._rate_budget()
        for _ in range(10):
            first._api("repos/example/eco-tom/read-only-evidence")
            second._api("repos/example/eco-tom/read-only-evidence")
        self.assertEqual(available, 190)
        # A worst-case burst of ten 120-request profiles includes native polling,
        # final collection and publication checks, with no assumed idle reset.
        for incident in range(10):
            # Make the shared reset reachable within this controller's deadline.
            self.clock.now = max(self.clock.now, len(windows) * 3600 - 300)
            validator = self.validator(service)
            validator.sleep = sleep
            for _ in range(120):
                validator._api("repos/example/eco-tom/read-only-evidence")
        self.assertGreater(len(windows), 1)
        self.assertTrue(all(count <= 1000 for count in windows))
        self.assertGreater(probes, 10)
        self.assertTrue(self.clock.sleeps)


class NativeContractTests(unittest.TestCase):
    def derive(self, raw):
        return native.derive_native_contract(raw, repository=REPOSITORY, base_sha=BASE, workflow_path=PATH,
                                             package_slug="sample", source_digest="d" * 64)

    def test_trusted_repo_workflow_can_derive_real_names_without_test_counts(self):
        raw = (ROOT / ".github/workflows/test-zlib.yml").read_bytes()
        contract = native.derive_native_contract(raw, repository=REPOSITORY, base_sha=BASE,
            workflow_path=".github/workflows/test-zlib.yml", package_slug="zlib", source_digest=digest(raw), called_job="test-zlib")
        self.assertEqual(contract["called_job"], "test-zlib")
        self.assertEqual(contract["job_name"], "test-zlib")
        self.assertEqual(contract["gate_step"], "Calculate test summary")
        self.assertIn("Regression applicability - package manager installed", contract["mandatory_steps"])

    def test_optional_test6_literal_job_name_and_explicit_gate(self):
        for test6 in (True, False):
            api = GitHubFixture(source_workflow(test6=test6, job_name="Standalone native sample", explicit_gate=True))
            clock = Clock()
            receipt = native.NativeValidation(api, clock=clock, sleep=clock.sleep).dispatch_and_wait(api.stage, api.contract)
            self.assertEqual(len(api.contract["mandatory_steps"]), 6 if test6 else 5)
            self.assertEqual(api.contract["gate_step"], "Enforce failure status")
            self.assertEqual(receipt["job"]["name"], "Standalone native sample")

    def test_yaml_parser_rejects_duplicate_keys_aliases_tags_and_malformed_documents(self):
        invalid = [b"name: one\nname: two\n", b"name: &x value\nother: *x\n", b"!!python/object:os.system {}",
                   b"[]", b"null", b"\xff", b"name: [", b"---\nname: one\n---\nname: two\n", b"",
                   b"x" * (native.MAX_WORKFLOW_BYTES + 1), "not bytes"]
        for raw in invalid:
            with self.subTest(raw=str(raw)[:50]):
                with self.assertRaises(ContractError):
                    self.derive(raw)

    def test_unsafe_or_ambiguous_workflow_contracts_are_refused(self):
        def job(flow):
            return flow["jobs"]["test-sample"]
        mutations = [lambda flow: flow.pop("permissions"), lambda flow: flow.update(permissions="read-all"),
                     lambda flow: flow.update(permissions={"contents": "write"}),
                     lambda flow: flow["on"].update(push=None), lambda flow: flow["on"].pop("workflow_dispatch"),
                     lambda flow: flow["on"].update(workflow_dispatch={"inputs": {"ref": {"required": True}}}),
                     lambda flow: flow["jobs"].update(extra=deepcopy(job(flow))),
                     lambda flow: job(flow).update(**{"runs-on": [native.RUNNER]}),
                     lambda flow: job(flow).update(**{"runs-on": "ubuntu-latest"}),
                     lambda flow: job(flow).update(**{"continue-on-error": True}),
                     lambda flow: job(flow).update(**{"timeout-minutes": 61}),
                     lambda flow: job(flow).update(name="${{ inputs.name }}"),
                     lambda flow: job(flow)["steps"][1].update(name=job(flow)["steps"][2]["name"]),
                     lambda flow: job(flow)["steps"][1].update(id="test2"),
                     lambda flow: job(flow)["steps"][1].update(name="Set up job"),
                     lambda flow: job(flow)["steps"].pop(1),
                     lambda flow: job(flow)["steps"][-2].pop("if"),
                     lambda flow: job(flow)["steps"][-2].update(**{"continue-on-error": True}),
                     lambda flow: job(flow)["steps"][-2].update(run=""),
                     lambda flow: job(flow)["steps"][-2].update(id="not-summary"),
                     lambda flow: job(flow)["steps"][1].update(uses="evil/action@main")]
        mutations.append(lambda flow: job(flow)["steps"][-3].update(id="other", name="Test 6 - Regression probe"))
        mutations += [lambda flow, key=key: job(flow).update({key: "not-allowed"}) for key in
                      ("strategy", "uses", "needs", "if", "container", "services", "environment")]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                flow = source_workflow()
                mutation(flow)
                with self.assertRaises(ContractError):
                    self.derive(encode_source(flow))


class NativeCliTests(unittest.TestCase):
    def test_input_and_output_links_and_nonregular_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.json"
            original.write_bytes(b'{"protected":true}')
            symlink = Path(directory) / "symlink.json"
            symlink.symlink_to(original)
            hardlink = Path(directory) / "hardlink.json"
            os.link(original, hardlink)
            fifo = Path(directory) / "fifo.json"
            os.mkfifo(fifo)
            for path in (original, symlink, hardlink, fifo, Path(directory)):
                with self.subTest(path=path.name):
                    with self.assertRaises((ContractError, OSError)):
                        native._load(path)
                    with self.assertRaises((ContractError, OSError)):
                        native._write(path, {"status": "passed"})
            self.assertEqual(original.read_bytes(), b'{"protected":true}')

    def test_cli_imports_helpers_in_isolated_mode(self):
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(ROOT / ".github/scripts/smoke_repair_native.py"), "--help"],
            check=False, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--mode", result.stdout)

    def test_strict_json_inputs_reject_duplicates_nonfinite_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b"\xff", b" " * (native.MAX_DOCUMENT_BYTES + 1)):
                source.write_bytes(raw)
                with self.assertRaises(ContractError):
                    native._load(source)

    def test_cli_dispatch_then_verify_is_offline(self):
        api = GitHubFixture()
        with tempfile.TemporaryDirectory() as directory:
            stage, contract, output = [Path(directory) / name for name in ("stage.json", "contract.json", "receipt.json")]
            stage.write_text(json.dumps(api.stage))
            contract.write_text(json.dumps(api.contract))
            arguments = ["--stage", str(stage), "--contract", str(contract), "--output", str(output)]
            with patch.object(native, "GitHub", return_value=api):
                self.assertEqual(native.main(["--mode", "dispatch", *arguments]), 0)
                saved = json.loads(output.read_text())
                self.assertEqual(native.main(["--mode", "verify", *arguments]), 0)
                self.assertEqual(json.loads(output.read_text()), saved)
            self.assertEqual(len(api.posts), 1)

    def test_cli_failure_does_not_emit_a_pass(self):
        api = GitHubFixture()
        api.main_sha = "f" * 40
        with tempfile.TemporaryDirectory() as directory:
            stage, contract, output = [Path(directory) / name for name in ("stage.json", "contract.json", "receipt.json")]
            stage.write_text(json.dumps(api.stage))
            contract.write_text(json.dumps(api.contract))
            with patch.object(native, "GitHub", return_value=api), patch("sys.stderr", new_callable=io.StringIO) as error:
                status = native.main(["--mode", "dispatch", "--stage", str(stage), "--contract", str(contract), "--output", str(output)])
            self.assertEqual(status, 1)
            self.assertIn("not passed", error.getvalue())
            self.assertEqual(json.loads(output.read_text())["status"], "not_passed")
            self.assertEqual(api.posts, [])

    def test_cli_bad_sha_clears_stale_success_receipt(self):
        api = GitHubFixture()
        clock = Clock()
        receipt = native.NativeValidation(api, clock=clock, sleep=clock.sleep).dispatch_and_wait(api.stage, api.contract)
        api.branch_sha = "f" * 40
        with tempfile.TemporaryDirectory() as directory:
            stage, contract, output = [Path(directory) / name for name in ("stage.json", "contract.json", "receipt.json")]
            stage.write_text(json.dumps(api.stage))
            contract.write_text(json.dumps(api.contract))
            output.write_text(json.dumps(receipt))
            with patch.object(native, "GitHub", return_value=api), patch("sys.stderr", new_callable=io.StringIO):
                status = native.main(["--mode", "verify", "--stage", str(stage), "--contract", str(contract), "--output", str(output)])
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(output.read_text())["status"], "not_passed")
            self.assertEqual(len(api.posts), 1)

    def test_cli_output_cannot_overwrite_stage_or_contract(self):
        api = GitHubFixture()
        with tempfile.TemporaryDirectory() as directory:
            stage, contract = [Path(directory) / name for name in ("stage.json", "contract.json")]
            stage.write_text(json.dumps(api.stage))
            contract.write_text(json.dumps(api.contract))
            for output in (stage, contract):
                before = output.read_bytes()
                with patch.object(native, "GitHub") as github, patch("sys.stderr", new_callable=io.StringIO):
                    result = native.main(["--mode", "dispatch", "--stage", str(stage), "--contract", str(contract), "--output", str(output)])
                self.assertEqual(result, 1)
                self.assertEqual(output.read_bytes(), before)
                github.assert_not_called()


if __name__ == "__main__":
    unittest.main()
