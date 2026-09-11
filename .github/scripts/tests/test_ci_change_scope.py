from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "ci_change_scope.py"
SPEC = importlib.util.spec_from_file_location("ci_change_scope", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)

REPOSITORY = "example/dashboard"
API_PREFIX = f"repos/{REPOSITORY}/actions"
WORKFLOW_ENDPOINT = f"{API_PREFIX}/workflows/main.yml"
LISTING_ENDPOINT = f"{WORKFLOW_ENDPOINT}/runs?branch=main&per_page=50&page=1"


def deployment_run(run_id=101, *, sha="a" * 40, attempt=2):
    return {
        "id": run_id, "run_number": run_id, "run_attempt": attempt,
        "workflow_id": 7, "path": ".github/workflows/main.yml",
        "head_sha": sha, "head_branch": "main", "event": "push",
        "status": "completed", "conclusion": "success",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    }


def deployment_documents(runs, *, skipped=()):
    documents = {f"{API_PREFIX}/workflows/main.yml": {
        "id": 7, "path": ".github/workflows/main.yml",
    }}
    for start in range(0, max(1, len(runs)), 50):
        documents[f"{API_PREFIX}/workflows/main.yml/runs?branch=main&per_page=50&page={start // 50 + 1}"] = {
            "total_count": len(runs), "workflow_runs": copy.deepcopy(runs[start:start + 50]),
        }
    for run in runs:
        endpoint = f"{API_PREFIX}/runs/{run['id']}/attempts/{run['run_attempt']}"
        documents[endpoint] = copy.deepcopy(run)
        job = {
            "id": run["id"] * 10, "run_id": run["id"], "run_attempt": run["run_attempt"],
            "head_sha": run["head_sha"], "name": "Build and deploy reviewed main",
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{run['id'] * 10}",
            "run_url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run['id']}",
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}/job/{run['id'] * 10}",
            "status": "completed", "conclusion": "success",
            "steps": [{"name": name, "status": "completed", "conclusion": "success"} for name in (
                "Require reviewed generated site data", "Require the reviewed commit to remain current", "Deploy to S3",
            )],
        }
        if run["id"] in skipped:
            job.update(conclusion="skipped", steps=[])
        documents[f"{endpoint}/jobs?per_page=100&page=1"] = {"total_count": 1, "jobs": [job]}
    return documents


def deployment_api(*snapshots):
    index = -1

    def read(endpoint):
        nonlocal index
        if endpoint == WORKFLOW_ENDPOINT:
            index = min(index + 1, len(snapshots) - 1)
        return copy.deepcopy(snapshots[index][endpoint])

    return Mock(side_effect=read)


class DeploymentReceiptTests(unittest.TestCase):
    def setUp(self):
        self.run = deployment_run()
        self.documents = deployment_documents([self.run])
        self.endpoint = f"{API_PREFIX}/runs/101/attempts/2"
        self.jobs_endpoint = self.endpoint + "/jobs?per_page=100&page=1"

    def receipt(self):
        self.api = Mock(side_effect=lambda endpoint: copy.deepcopy(self.documents[endpoint]))
        return scope.latest_deployment_receipt(REPOSITORY, self.api)

    def test_exact_successful_attempt_with_real_deploy_step_is_a_receipt(self):
        self.assertEqual(self.receipt(), {"run_id": 101, "run_attempt": 2, "sha": "a" * 40})
        self.assertIn(self.jobs_endpoint, [call.args[0] for call in self.api.call_args_list])
        self.assertTrue(all("filter=all" not in call.args[0] for call in self.api.call_args_list))
        self.assertEqual(self.api.call_count, 4)

    def test_mutable_state_change_restarts_the_full_lookup(self):
        for status, conclusion in (("in_progress", None), ("queued", None), ("completed", "failure")):
            with self.subTest(status=status, conclusion=conclusion):
                first = copy.deepcopy(self.documents)
                first[LISTING_ENDPOINT]["workflow_runs"][0].update(status=status, conclusion=conclusion)
                api = deployment_api(first, self.documents)
                self.assertEqual(scope.latest_deployment_receipt(REPOSITORY, api), {
                    "run_id": 101, "run_attempt": 2, "sha": "a" * 40,
                })
                self.assertEqual([call.args[0] for call in api.call_args_list], [
                    WORKFLOW_ENDPOINT, LISTING_ENDPOINT, self.endpoint,
                    WORKFLOW_ENDPOINT, LISTING_ENDPOINT, self.endpoint, self.jobs_endpoint,
                ])

    def test_restart_rechecks_newer_runs_and_recomputes_catch_up(self):
        newer = deployment_run(102, sha="b" * 40)
        stable = deployment_documents([newer, self.run])
        first = copy.deepcopy(stable)
        for run in first[LISTING_ENDPOINT]["workflow_runs"]:
            run.update(status="in_progress", conclusion=None)
        newer_endpoint = f"{API_PREFIX}/runs/102/attempts/2"
        first[newer_endpoint].update(status="in_progress", conclusion=None)
        api = deployment_api(first, stable)
        self.assertEqual(scope.latest_deployment_receipt(REPOSITORY, api), {
            "run_id": 102, "run_attempt": 2, "sha": "b" * 40,
        })
        self.assertEqual([call.args[0] for call in api.call_args_list].count(newer_endpoint), 2)

    def test_persistent_mutable_churn_exhausts_three_full_lookups(self):
        self.documents[LISTING_ENDPOINT]["workflow_runs"][0].update(status="in_progress", conclusion=None)
        api = deployment_api(self.documents)
        with self.assertRaisesRegex(scope.ScopeError, "did not stabilize after 3 lookup attempts"):
            scope.latest_deployment_receipt(REPOSITORY, api)
        self.assertEqual([call.args[0] for call in api.call_args_list], [
            WORKFLOW_ENDPOINT, LISTING_ENDPOINT, self.endpoint,
        ] * 3)

    def test_mutable_churn_does_not_retry_identity_mismatch(self):
        for key, value in (
            ("id", 102), ("run_attempt", 1), ("head_sha", "b" * 40), ("run_number", 102),
            ("event", "workflow_dispatch"), ("workflow_id", 99),
            ("repository", {"full_name": "other/repo"}),
        ):
            with self.subTest(key=key):
                first = copy.deepcopy(self.documents)
                first[LISTING_ENDPOINT]["workflow_runs"][0].update(status="in_progress", conclusion=None)
                first[self.endpoint][key] = value
                api = deployment_api(first, self.documents)
                with self.assertRaises(scope.ScopeError):
                    scope.latest_deployment_receipt(REPOSITORY, api)
                self.assertEqual(api.call_count, 3)

    def test_invalid_responses_are_not_retried(self):
        for endpoint, key, value in (
            (LISTING_ENDPOINT, "total_count", True), (LISTING_ENDPOINT, "total_count", 2),
            (LISTING_ENDPOINT, "workflow_runs", [None]),
            (self.endpoint, "status", "in_progress"),
            (self.jobs_endpoint, "total_count", 2),
            (self.jobs_endpoint, "jobs", []),
        ):
            with self.subTest(endpoint=endpoint, key=key):
                first = copy.deepcopy(self.documents)
                first[endpoint][key] = value
                api = deployment_api(first, self.documents)
                with self.assertRaises(scope.ScopeError):
                    scope.latest_deployment_receipt(REPOSITORY, api)
                self.assertEqual([call.args[0] for call in api.call_args_list].count(WORKFLOW_ENDPOINT), 1)

    def test_pagination_churn_restarts_at_page_one_and_finds_newest_receipt(self):
        runs = [deployment_run(run_id) for run_id in range(151, 100, -1)]
        skipped = set(range(102, 152))
        stable = deployment_documents([deployment_run(152, sha="b" * 40), *runs], skipped=skipped)
        page_two = LISTING_ENDPOINT.removesuffix("1") + "2"
        for count, tail in (
            (52, runs[-2:]), (50, []), (51, [runs[-2]]), (51, [deployment_run(152)]),
        ):
            with self.subTest(count=count, tail=tail):
                first = deployment_documents(runs, skipped=skipped)
                first[page_two] = {"total_count": count, "workflow_runs": tail}
                api = deployment_api(first, stable)
                self.assertEqual(scope.latest_deployment_receipt(REPOSITORY, api)["run_id"], 152)
                calls = [call.args[0] for call in api.call_args_list]
                self.assertEqual(calls[calls.index(page_two) + 1:calls.index(page_two) + 3], [
                    WORKFLOW_ENDPOINT, LISTING_ENDPOINT,
                ])
                self.assertEqual(calls.count(page_two), 1)
                self.assertNotIn(self.jobs_endpoint, calls)

    def test_pagination_churn_cannot_hide_invalid_or_conflicting_identities(self):
        runs = [deployment_run(run_id) for run_id in range(151, 100, -1)]
        stable = deployment_documents(runs, skipped=set(range(102, 152)))
        page_two = LISTING_ENDPOINT.removesuffix("1") + "2"
        for tail in ([None, runs[-1]], [dict(runs[-2], head_sha="b" * 40), runs[-1]]):
            with self.subTest(tail=tail):
                first = copy.deepcopy(stable)
                first[page_two] = {"total_count": 52, "workflow_runs": tail}
                api = deployment_api(first, stable)
                with self.assertRaises(scope.ScopeError):
                    scope.latest_deployment_receipt(REPOSITORY, api)
                calls = [call.args[0] for call in api.call_args_list]
                self.assertEqual(calls.count(WORKFLOW_ENDPOINT), 1)
                self.assertEqual(calls[-1], page_two)

    def test_persistent_pagination_churn_exhausts_three_full_lookups(self):
        runs = [deployment_run(run_id) for run_id in range(151, 100, -1)]
        documents = deployment_documents(runs, skipped=set(range(102, 152)))
        page_two = LISTING_ENDPOINT.removesuffix("1") + "2"
        documents[page_two] = {"total_count": 51, "workflow_runs": [runs[-2]]}
        api = deployment_api(documents)
        with self.assertRaisesRegex(scope.ScopeError, "did not stabilize after 3 lookup attempts"):
            scope.latest_deployment_receipt(REPOSITORY, api)
        calls = [call.args[0] for call in api.call_args_list]
        self.assertEqual(calls.count(WORKFLOW_ENDPOINT), 3)
        self.assertEqual(calls.count(LISTING_ENDPOINT), 3)
        self.assertEqual(calls.count(page_two), 3)
        self.assertNotIn(self.endpoint, calls)

    def test_duplicate_or_unordered_runs_within_one_page_are_not_retried(self):
        for runs in ([self.run, self.run], [self.run, deployment_run(102)]):
            with self.subTest(runs=runs):
                api = deployment_api(deployment_documents(runs), self.documents)
                with self.assertRaisesRegex(scope.ScopeError, "duplicate or unordered"):
                    scope.latest_deployment_receipt(REPOSITORY, api)
                self.assertEqual(api.call_count, 2)

    def test_retries_share_the_original_api_request_and_time_budgets(self):
        self.documents[LISTING_ENDPOINT]["workflow_runs"][0].update(status="in_progress", conclusion=None)
        for budget in ("requests", "deadline"):
            with self.subTest(budget=budget), patch.dict(os.environ, {"GH_TOKEN": "fixture-only"}), patch.object(
                scope.time, "monotonic", return_value=0
            ) as clock:
                fixture = deployment_api(self.documents)

                def response(command, **kwargs):
                    document = fixture(command[-1])
                    if budget == "deadline":
                        if fixture.call_count == 3:
                            clock.return_value = 119
                        elif fixture.call_count == 4:
                            self.assertEqual(kwargs["timeout"], 1)
                            clock.return_value = 120
                    return json.dumps(document).encode()

                api = scope.GitHubReadAPI(REPOSITORY)
                if budget == "requests":
                    api.requests = 124
                with patch.object(scope, "read_api_response", side_effect=response), self.assertRaisesRegex(
                    scope.ScopeError, "API read budget exhausted"
                ):
                    scope.latest_deployment_receipt(REPOSITORY, api)
                self.assertEqual(api.deadline, 120)
                self.assertEqual(api.requests, 128 if budget == "requests" else 4)
                self.assertEqual([call.args[0] for call in fixture.call_args_list], [
                    WORKFLOW_ENDPOINT, LISTING_ENDPOINT, self.endpoint, WORKFLOW_ENDPOINT,
                ])

    def test_newer_scope_only_green_run_is_not_a_deployment(self):
        self.documents = deployment_documents([deployment_run(102), self.run], skipped={102})
        receipt = self.receipt()
        self.assertEqual(receipt["run_id"], 101)
        self.assertNotIn("requires_catch_up", receipt)

    def test_newer_failed_cancelled_or_live_attempt_requires_catch_up(self):
        for status, conclusion in (
            ("completed", "failure"), ("completed", "cancelled"), ("completed", "timed_out"),
            ("in_progress", None), ("queued", None), ("waiting", None),
        ):
            with self.subTest(status=status, conclusion=conclusion):
                newer = deployment_run(102, sha="b" * 40)
                newer.update(status=status, conclusion=conclusion)
                self.documents = deployment_documents([newer, self.run])
                receipt = self.receipt()
                self.assertEqual(receipt["sha"], "a" * 40)
                self.assertTrue(receipt["requires_catch_up"])
                self.assertFalse(any("status=success" in call.args[0] for call in self.api.call_args_list))

    def test_older_failure_does_not_poison_a_newer_successful_receipt(self):
        older = deployment_run(100)
        older.update(conclusion="failure")
        self.documents = deployment_documents([self.run, older])
        self.assertNotIn("requires_catch_up", self.receipt())

    def test_current_activation_does_not_itself_require_deployment(self):
        current = deployment_run(102, sha="c" * 40, attempt=1)
        current.update(status="in_progress", conclusion=None)
        documents = deployment_documents([current, self.run])
        api = Mock(side_effect=lambda endpoint: copy.deepcopy(documents[endpoint]))
        receipt = scope.latest_deployment_receipt(REPOSITORY, api, current_run=(102, 1, "c" * 40))
        self.assertNotIn("requires_catch_up", receipt)
        self.assertFalse(any("runs/102/attempts" in call.args[0] for call in api.call_args_list))

    def test_current_rerun_cannot_hide_an_earlier_possibly_writing_attempt(self):
        current = deployment_run(102, sha="c" * 40, attempt=2)
        current.update(status="in_progress", conclusion=None)
        for runs in ([current, self.run], [self.run]):
            with self.subTest(current_listed=len(runs) == 2):
                documents = deployment_documents(runs)
                api = lambda endpoint: copy.deepcopy(documents[endpoint])
                receipt = scope.latest_deployment_receipt(REPOSITORY, api, current_run=(102, 2, "c" * 40))
                self.assertTrue(receipt["requires_catch_up"])

    def test_wrong_current_run_attempt_sha_or_completed_state_fails_closed(self):
        current = deployment_run(102, sha="c" * 40, attempt=1)
        current.update(status="in_progress", conclusion=None)
        documents = deployment_documents([current, self.run])
        api = lambda endpoint: copy.deepcopy(documents[endpoint])
        for identity in ((102, 2, "c" * 40), (102, 1, "d" * 40), (True, 1, "c" * 40)):
            with self.subTest(identity=identity), self.assertRaises(scope.ScopeError):
                scope.latest_deployment_receipt(REPOSITORY, api, current_run=identity)
        current.update(status="completed", conclusion="success")
        documents = deployment_documents([current, self.run])
        with self.assertRaises(scope.ScopeError):
            scope.latest_deployment_receipt(REPOSITORY, api, current_run=(102, 1, "c" * 40))

    def test_other_live_execution_is_not_excluded_as_current_activation(self):
        other = deployment_run(102, sha="b" * 40, attempt=1)
        other.update(status="in_progress", conclusion=None)
        documents = deployment_documents([other, self.run])
        api = lambda endpoint: copy.deepcopy(documents[endpoint])
        receipt = scope.latest_deployment_receipt(REPOSITORY, api, current_run=(103, 1, "c" * 40))
        self.assertTrue(receipt["requires_catch_up"])

    def test_skipped_deploy_step_is_not_a_receipt(self):
        self.documents[self.jobs_endpoint]["jobs"][0]["steps"][-1]["conclusion"] = "skipped"
        with self.assertRaisesRegex(scope.ScopeError, "No verified S3"):
            self.receipt()

    def test_wrong_run_identity_and_incomplete_completion_fail_closed(self):
        mutations = (
            ("id", 102), ("run_attempt", 1), ("workflow_id", 99), ("run_number", 102),
            ("path", ".github/workflows/content-deploy.yml"), ("head_branch", "production"),
            ("head_sha", "b" * 40), ("head_sha", "0" * 40), ("head_sha", "not-a-sha"),
            ("repository", {"full_name": "other/repo"}),
            ("head_repository", {"full_name": "fork/dashboard"}),
            ("status", "in_progress"), ("conclusion", "failure"), ("event", "pull_request"),
        )
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                self.documents = deployment_documents([self.run])
                self.documents[self.endpoint][key] = value
                with self.assertRaises(scope.ScopeError):
                    self.receipt()

    def test_wrong_workflow_identity_fails_closed(self):
        self.documents[f"{API_PREFIX}/workflows/main.yml"]["path"] = ".github/workflows/other.yml"
        with self.assertRaisesRegex(scope.ScopeError, "workflow identity"):
            self.receipt()

    def test_boolean_float_and_string_ids_fail_closed_everywhere(self):
        listing = f"{API_PREFIX}/workflows/main.yml/runs?branch=main&per_page=50&page=1"
        targets = (
            (f"{API_PREFIX}/workflows/main.yml", (), "id"),
            (listing, (), "total_count"),
            *[(listing, ("workflow_runs", 0), key) for key in ("id", "workflow_id", "run_number", "run_attempt")],
            *[(self.endpoint, (), key) for key in ("id", "workflow_id", "run_number", "run_attempt")],
            *[(self.jobs_endpoint, ("jobs", 0), key) for key in ("id", "run_id", "run_attempt")],
            (self.jobs_endpoint, (), "total_count"),
        )
        for endpoint, path, key in targets:
            for value in (True, False, 1.0, "1"):
                with self.subTest(endpoint=endpoint, path=path, key=key, value=value):
                    self.documents = deployment_documents([self.run])
                    target = self.documents[endpoint]
                    for component in path:
                        target = target[component]
                    target[key] = value
                    with self.assertRaises(scope.ScopeError):
                        self.receipt()

    def test_malformed_older_listed_record_is_not_silently_ignored(self):
        listing = f"{API_PREFIX}/workflows/main.yml/runs?branch=main&per_page=50&page=1"
        for bad_record in (None, [], {}, deployment_run(100, attempt=True)):
            with self.subTest(record=bad_record):
                self.documents = deployment_documents([self.run, deployment_run(100)])
                self.documents[listing]["workflow_runs"][1] = bad_record
                with self.assertRaises(scope.ScopeError):
                    self.receipt()

    def test_job_urls_must_bind_the_same_repository_run_and_job(self):
        for key, value in (
            ("url", "https://api.github.com/repos/other/repo/actions/jobs/1010"),
            ("url", "https://api.github.com/repos/example/dashboard/actions/jobs/999"),
            ("run_url", "https://api.github.com/repos/example/dashboard/actions/runs/999"),
            ("html_url", "https://github.com/example/dashboard/actions/runs/999/job/1010"),
            ("html_url", "https://github.com/other/repo/actions/runs/101/job/1010"),
            ("html_url", "https://github.com/example/dashboard/actions/runs/101/job/999"),
            ("html_url", "https://github.com/example/dashboard/actions/runs/101/job/1010?spoofed=1"),
            ("html_url", "https://github.com.evil.example/example/dashboard/actions/runs/101/job/1010"),
        ):
            with self.subTest(key=key, value=value):
                self.documents = deployment_documents([self.run])
                self.documents[self.jobs_endpoint]["jobs"][0][key] = value
                with self.assertRaises(scope.ScopeError):
                    self.receipt()

    def test_wrong_job_binding_or_completion_fails_closed(self):
        for key, value in (
            ("id", True), ("run_id", 102), ("run_attempt", 1), ("head_sha", "b" * 40),
            ("status", "in_progress"), ("conclusion", "failure"),
        ):
            with self.subTest(key=key):
                self.documents = deployment_documents([self.run])
                self.documents[self.jobs_endpoint]["jobs"][0][key] = value
                with self.assertRaises(scope.ScopeError):
                    self.receipt()

    def test_missing_duplicate_or_unfinished_steps_cannot_prove_deployment(self):
        for change in ("missing", "duplicate", "failed", "unfinished", "unreviewed"):
            with self.subTest(change=change):
                self.documents = deployment_documents([self.run])
                steps = self.documents[self.jobs_endpoint]["jobs"][0]["steps"]
                if change == "missing":
                    steps.pop()
                elif change == "duplicate":
                    steps.append(copy.deepcopy(steps[-1]))
                elif change == "failed":
                    steps[-1]["conclusion"] = "failure"
                elif change == "unfinished":
                    steps[-1]["status"] = "in_progress"
                else:
                    steps[0]["conclusion"] = "skipped"
                with self.assertRaises(scope.ScopeError):
                    self.receipt()

    def test_duplicate_jobs_fail_closed(self):
        document = self.documents[self.jobs_endpoint]
        document["jobs"].append(copy.deepcopy(document["jobs"][0]))
        document["total_count"] = 2
        with self.assertRaises(scope.ScopeError):
            self.receipt()

    def test_incomplete_run_or_job_pages_fail_closed(self):
        listing = f"{API_PREFIX}/workflows/main.yml/runs?branch=main&per_page=50&page=1"
        for endpoint in (listing, self.jobs_endpoint):
            with self.subTest(endpoint=endpoint):
                self.documents = deployment_documents([self.run])
                self.documents[endpoint]["total_count"] += 1
                with self.assertRaises(scope.ScopeError):
                    self.receipt()

    def test_pagination_finds_older_actual_receipt_without_trusting_green_scopes(self):
        runs = [deployment_run(run_id) for run_id in range(151, 100, -1)]
        self.documents = deployment_documents(runs, skipped=set(range(102, 152)))
        self.assertEqual(self.receipt()["run_id"], 101)
        self.assertTrue(any("page=2" in call.args[0] for call in self.api.call_args_list))

    def test_no_receipt_and_bounded_history_exhaustion_require_reviewed_bootstrap(self):
        for runs in ([], [deployment_run(run_id) for run_id in range(351, 100, -1)]):
            with self.subTest(count=len(runs)):
                self.documents = deployment_documents(runs, skipped={run["id"] for run in runs})
                with self.assertRaisesRegex(scope.ScopeError, "approved, enabled manual"):
                    self.receipt()
                self.assertFalse(any("page=6" in call.args[0] for call in self.api.call_args_list))

    def test_api_is_authenticated_bounded_read_only_and_cannot_follow_other_urls(self):
        with patch.dict(os.environ, {"GH_TOKEN": "fixture-only"}), patch.object(
            scope, "read_api_response", return_value=b"{}"
        ) as command:
            api = scope.GitHubReadAPI(REPOSITORY)
            api(f"{API_PREFIX}/workflows/main.yml")
            args, = command.call_args.args
            self.assertEqual(args[:7], ["gh", "api", "--hostname", "github.com", "--method", "GET", f"{API_PREFIX}/workflows/main.yml"])
            self.assertLessEqual(command.call_args.kwargs["timeout"], 15)
            for endpoint in ("https://evil.example/path", "repos/other/repo/actions/runs", f"{API_PREFIX}/../secrets"):
                with self.assertRaises(scope.ScopeError):
                    api(endpoint)
            api.requests = 128
            with self.assertRaisesRegex(scope.ScopeError, "budget"):
                api(f"{API_PREFIX}/workflows/main.yml")
            self.assertEqual(command.call_count, 1)

    def test_missing_credentials_failed_requests_and_malformed_json_fail_closed(self):
        with patch.dict(os.environ, {"GH_TOKEN": ""}):
            with self.assertRaisesRegex(scope.ScopeError, "GH_TOKEN"):
                scope.GitHubReadAPI(REPOSITORY)
        with patch.dict(os.environ, {"GH_TOKEN": "fixture-only"}):
            for body in (b"bad json", b"[]"):
                with self.subTest(body=body), patch.object(
                    scope, "read_api_response", return_value=body
                ), self.assertRaises(scope.ScopeError):
                    scope.GitHubReadAPI(REPOSITORY)(f"{API_PREFIX}/workflows/main.yml")

    def test_api_response_is_bounded_before_json_parsing(self):
        for size in (scope.MAX_API_RESPONSE_BYTES, scope.MAX_API_RESPONSE_BYTES + 1):
            with self.subTest(size=size):
                command = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(b' ' * {size})"]
                if size == scope.MAX_API_RESPONSE_BYTES:
                    self.assertEqual(len(scope.read_api_response(command, environment=os.environ.copy(), timeout=5)), size)
                else:
                    with self.assertRaisesRegex(scope.ScopeError, "byte limit"):
                        scope.read_api_response(command, environment=os.environ.copy(), timeout=5)

    def test_failed_or_stalled_api_process_is_not_a_receipt(self):
        for program, expected in (("raise SystemExit(1)", "request failed"), ("import time; time.sleep(5)", "timed out")):
            with self.subTest(program=program), self.assertRaisesRegex(scope.ScopeError, expected):
                scope.read_api_response([sys.executable, "-c", program], environment=os.environ.copy(), timeout=0.2)


class DeploymentReceiptCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "github-output"
        self.output.write_text("existing=reviewed\n")
        self.run = deployment_run()
        self.current = dict(deployment_run(999, sha="c" * 40, attempt=1), status="in_progress", conclusion=None)
        self.stable = deployment_documents([self.current, self.run])
        self.first = copy.deepcopy(self.stable)
        self.first[LISTING_ENDPOINT]["workflow_runs"][1].update(status="in_progress", conclusion=None)

    def invoke(self, api, *, changes=None, attempt=1):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {
            "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_RUN_ID": "999", "GITHUB_RUN_ATTEMPT": str(attempt),
        }), patch.object(scope, "GitHubReadAPI", return_value=api) as client, patch.object(
            scope, "changed_paths", side_effect=changes or [["layouts/index.html"], ["layouts/index.html"]]
        ) as diff, redirect_stdout(stdout), redirect_stderr(stderr):
            status = scope.main([
                "--base", "b" * 40, "--head", "c" * 40, "--deployed-baseline", "--github-output", str(self.output),
            ])
        client.assert_called_once_with(REPOSITORY)
        return status, stdout.getvalue(), stderr.getvalue(), diff

    def test_completion_between_list_and_detail_recovers_dashboard_activation(self):
        api = deployment_api(self.first, self.stable)
        status, stdout, stderr, diff = self.invoke(api)
        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout), {
            "smoke": False, "dashboard": True,
            "deployment_receipt": {"run_id": 101, "run_attempt": 2, "sha": "a" * 40},
        })
        self.assertEqual(self.output.read_text(), "existing=reviewed\nsmoke=false\ndashboard=true\n")
        self.assertEqual([call.args for call in diff.call_args_list], [("b" * 40, "c" * 40), ("a" * 40, "c" * 40)])
        self.assertEqual([call.args[0] for call in api.call_args_list].count(LISTING_ENDPOINT), 2)

    def test_exhausted_churn_never_emits_or_appends_partial_scope_outputs(self):
        api = deployment_api(self.first)
        status, stdout, stderr, diff = self.invoke(api)
        self.assertEqual(status, 1)
        self.assertIn("did not stabilize after 3 lookup attempts", stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(self.output.read_text(), "existing=reviewed\n")
        self.assertEqual(diff.call_count, 1)
        self.assertEqual([call.args[0] for call in api.call_args_list].count(LISTING_ENDPOINT), 3)

    def test_pagination_restart_routes_from_the_newest_verified_receipt(self):
        runs = [deployment_run(run_id) for run_id in range(151, 100, -1)]
        skipped = set(range(102, 152))
        first = deployment_documents(runs, skipped=skipped)
        page_two = LISTING_ENDPOINT.removesuffix("1") + "2"
        first[page_two] = {"total_count": 52, "workflow_runs": runs[-2:]}
        stable = deployment_documents([deployment_run(152, sha="b" * 40), *runs], skipped=skipped)
        api = deployment_api(first, stable)
        status, stdout, stderr, diff = self.invoke(api)
        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["deployment_receipt"]["run_id"], 152)
        self.assertIn("dashboard=true\n", self.output.read_text())
        self.assertEqual(diff.call_args.args, ("b" * 40, "c" * 40))
        self.assertEqual([call.args[0] for call in api.call_args_list].count(LISTING_ENDPOINT), 2)

    def test_recovered_receipt_does_not_bypass_deployed_baseline_diff_validation(self):
        api = deployment_api(self.first, self.stable)
        status, stdout, stderr, diff = self.invoke(api, changes=[
            ["layouts/index.html"], scope.ScopeError("deployed baseline is not an ancestor"),
        ])
        self.assertEqual(status, 1)
        self.assertIn("deployed baseline is not an ancestor", stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(self.output.read_text(), "existing=reviewed\n")
        self.assertEqual(diff.call_args.args, ("a" * 40, "c" * 40))

    def test_identity_mismatch_is_rejected_immediately_without_scope_outputs(self):
        self.output.unlink()
        self.first[f"{API_PREFIX}/runs/101/attempts/2"]["head_sha"] = "d" * 40
        api = deployment_api(self.first, self.stable)
        status, stdout, stderr, diff = self.invoke(api)
        self.assertEqual(status, 1)
        self.assertIn("deployment attempt contradicts the listed run", stderr)
        self.assertEqual(stdout, "")
        self.assertFalse(self.output.exists())
        self.assertEqual(diff.call_count, 1)
        self.assertEqual([call.args[0] for call in api.call_args_list].count(LISTING_ENDPOINT), 1)

    def test_recovered_lookup_still_requires_successful_deployment_steps(self):
        jobs_endpoint = f"{API_PREFIX}/runs/101/attempts/2/jobs?per_page=100&page=1"
        self.stable[jobs_endpoint]["jobs"][0]["steps"][-1]["conclusion"] = "skipped"
        api = deployment_api(self.first, self.stable)
        status, stdout, stderr, diff = self.invoke(api)
        self.assertEqual(status, 1)
        self.assertIn("No verified S3 deployment receipt", stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(self.output.read_text(), "existing=reviewed\n")
        self.assertEqual(diff.call_count, 1)
        self.assertEqual([call.args[0] for call in api.call_args_list].count(LISTING_ENDPOINT), 2)

    def test_recovered_failed_deployment_cannot_hide_behind_content_reversion(self):
        failed = dict(deployment_run(102, sha="b" * 40), conclusion="failure")
        stable = deployment_documents([self.current, failed, self.run])
        first = copy.deepcopy(stable)
        first[LISTING_ENDPOINT]["workflow_runs"][1].update(status="in_progress", conclusion=None)
        api = deployment_api(first, stable)
        status, stdout, stderr, _ = self.invoke(api, changes=[[".github/workflows/test-nginx.yml"], []])
        self.assertEqual(status, 0, stderr)
        result = json.loads(stdout)
        self.assertTrue(result["dashboard"])
        self.assertTrue(result["smoke"])
        self.assertTrue(result["deployment_receipt"]["requires_catch_up"])
        self.assertEqual(result["deployment_receipt"]["sha"], "a" * 40)

    def test_restart_preserves_current_rerun_catch_up_even_when_not_listed(self):
        for runs in ([dict(self.current, run_attempt=2), self.run], [self.run]):
            with self.subTest(current_listed=len(runs) == 2):
                stable = deployment_documents(runs)
                first = copy.deepcopy(stable)
                first[LISTING_ENDPOINT]["workflow_runs"][-1].update(status="in_progress", conclusion=None)
                api = deployment_api(first, stable)
                status, stdout, stderr, _ = self.invoke(api, changes=[[], []], attempt=2)
                self.assertEqual(status, 0, stderr)
                result = json.loads(stdout)
                self.assertTrue(result["dashboard"])
                self.assertTrue(result["deployment_receipt"]["requires_catch_up"])


class ClassificationTests(unittest.TestCase):
    def test_smoke_execution_closure_and_its_tests_do_not_deploy(self) -> None:
        paths = [
            ".github/workflows/test-nginx.yml",
            ".github/workflows/test-all-packages-batch23.yml",
            ".github/workflows/test-all-packages-summary.yml",
            ".github/workflows/test-all-packages-orchestrator.yml",
            ".github/scripts/tests/test_kvm_workflow.py",
            ".github/scripts/tests/test_pm_xpra_parquet_workflows.py",
            *scope.SMOKE_SCRIPTS,
            *scope.SMOKE_SUPPORT,
            *[f".github/actions/{name}/action.yml" for name in scope.SMOKE_ACTIONS],
            ".github/actions/apt-bootstrap/bootstrap.sh",
            ".github/actions/generic-source-regression-check/limited_cpu_probe.py",
            ".github/actions/publish-generated-data-pr/generated_data_pr.py",
            ".github/actions/publish-generated-data-pr/tests/test_orchestration_contract.py",
            ".github/scripts/tests/test_smoke_recovery.py",
        ]
        paths.extend(
            ".github/scripts/tests/test_" + Path(path).name
            for path in scope.SMOKE_SCRIPTS | scope.SMOKE_SUPPORT
            if path.endswith(".py") and "/tests/" not in path
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(
                    scope.classify_paths([path]), {"smoke": True, "dashboard": False}
                )

    def test_results_and_normal_dashboard_changes_never_start_smoke(self) -> None:
        paths = [
            "data/test-results/nginx.json", "data/test-results-index.json",
            "data/category_data.yml", "data/category_data_windows.yml",
            "data/recently_added_packages.yaml", "package_category_list.yml",
            "package_category_list_windows.yml", ".github/package-identity-catalog.json",
            "content/linux/opensource_packages/nginx.md", "content/windows/example.md",
            "layouts/index.html", "static/main.js", "assets/style.css",
            "config.toml", "config.cloudfront.toml", "package.json", "package-lock.json",
            "build_steps/update_category_mappings.py", "requirements.txt",
            ".github/workflows/main.yml", ".github/workflows/dashboard-ci.yml",
            ".github/scripts/generated_site_data_artifact.py",
            ".github/scripts/generated-site-data-requirements.txt",
            ".github/scripts/tests/test_generated_site_data_review_contract.py",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(
                    scope.classify_paths([path]), {"smoke": False, "dashboard": True}
                )

    def test_unknown_paths_build_conservatively(self) -> None:
        for path in (
            "README.md", ".github/actions/new-action/action.yml",
            ".github/scripts/new-helper.py", ".github/workflows/new-check.yml",
            ".github/workflows/nested/test-nginx.yml",
            "other/.github/workflows/test-nginx.yml",
            ".github/actions/apt-bootstrap-lookalike/action.yml",
            ".github/workflows/test-nginx.yml.bak",
            ".github/workflows/test-odd\nname.yml",
            ".github/workflows/test-nginx.yaml",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    scope.classify_paths([path]), {"smoke": False, "dashboard": True}
                )

    def test_mixed_changes_are_a_union_independent_of_order(self) -> None:
        paths = [".github/workflows/test-nginx.yml", "data/test-results/nginx.json"]
        for candidate in (paths, paths[::-1], paths * 2):
            self.assertEqual(
                scope.classify_paths(candidate), {"smoke": True, "dashboard": True}
            )

    def test_shared_router_changes_validate_both_routes(self) -> None:
        for path in (scope.ROUTING_SCRIPT, scope.ROUTING_TEST):
            self.assertEqual(
                scope.classify_paths([path]), {"smoke": True, "dashboard": True}
            )

    def test_empty_change_set_skips_both(self) -> None:
        self.assertEqual(scope.classify_paths([]), {"smoke": False, "dashboard": False})

    def test_invalid_paths_are_not_silent_skips(self) -> None:
        for path in ("", "/absolute", "../escape", "a/./b", "a//b"):
            with self.subTest(path=path), self.assertRaises(scope.ScopeError):
                scope.classify_paths([path])

    def test_incomplete_nul_diff_fails(self) -> None:
        with patch.object(scope, "validate_commit"), patch.object(
            scope, "git", side_effect=[b"", b"unterminated-path"]
        ), self.assertRaisesRegex(scope.ScopeError, "NUL-delimited"):
            scope.changed_paths("a" * 40, "b" * 40)


class GitScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repo"
        self.repository.mkdir()
        self.environment = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "CI Scope Test",
            "GIT_AUTHOR_EMAIL": "scope@example.invalid",
            "GIT_COMMITTER_NAME": "CI Scope Test",
            "GIT_COMMITTER_EMAIL": "scope@example.invalid",
        }
        self.git("init", "--initial-branch=main")
        self.write("README.md", "initial\n")
        self.base = self.commit()

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments], cwd=self.repository, env=self.environment,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def write(self, path: str, content: str = "changed\n") -> None:
        destination = self.repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    def commit(self) -> str:
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def invoke(self, base: str, head: str, *, cwd: Path | None = None):
        output = self.root / "github-output"
        return subprocess.run(
            [sys.executable, "-I", "-B", str(SCRIPT), "--base", base, "--head", head,
             "--github-output", str(output)],
            cwd=cwd or self.repository, env=self.environment, capture_output=True, text=True,
        )

    def assert_scope(self, base: str, head: str, expected: dict[str, bool]) -> None:
        result = self.invoke(base, head)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)
        lines = (self.root / "github-output").read_text().splitlines()
        self.assertEqual(lines[-2:], [f"{key}={str(value).lower()}" for key, value in expected.items()])

    def test_added_smoke_workflow(self) -> None:
        self.write(".github/workflows/test-nginx.yml")
        self.assert_scope(self.base, self.commit(), {"smoke": True, "dashboard": False})

    def test_deleted_smoke_workflow(self) -> None:
        self.write(".github/workflows/test-nginx.yml")
        base = self.commit()
        (self.repository / ".github/workflows/test-nginx.yml").unlink()
        self.assert_scope(base, self.commit(), {"smoke": True, "dashboard": False})

    def test_cross_scope_rename_counts_old_and_new_paths(self) -> None:
        self.write(".github/workflows/test-nginx.yml")
        base = self.commit()
        (self.repository / ".github/workflows/test-nginx.yml").rename(
            self.repository / "renamed-dashboard.yml"
        )
        self.git("config", "diff.renames", "true")
        self.assert_scope(base, self.commit(), {"smoke": True, "dashboard": True})

    def test_rename_into_smoke_scope_counts_both_paths(self) -> None:
        self.write(".github/workflows/normal.yml")
        base = self.commit()
        (self.repository / ".github/workflows/normal.yml").rename(
            self.repository / ".github/workflows/test-nginx.yml"
        )
        self.assert_scope(base, self.commit(), {"smoke": True, "dashboard": True})

    def test_large_result_promotion_never_starts_smoke(self) -> None:
        for index in range(1005):
            self.write(f"data/test-results/package-{index:04}.json", "{}\n")
        self.assert_scope(self.base, self.commit(), {"smoke": False, "dashboard": True})

    def test_smoke_after_hundreds_of_other_paths_is_not_lost(self) -> None:
        for index in range(350):
            self.write(f".a-first/package-{index:04}.json", "{}\n")
        self.write(".github/workflows/test-nginx.yml")
        self.assert_scope(self.base, self.commit(), {"smoke": True, "dashboard": True})

    def test_tabs_newlines_and_unicode_are_whole_paths(self) -> None:
        for path in ("data/tab\tfile.json", "data/new\nline.json", "data/\u03bb.json"):
            self.write(path)
        self.git("config", "core.quotePath", "true")
        self.assert_scope(self.base, self.commit(), {"smoke": False, "dashboard": True})

    def test_empty_valid_diff_is_not_an_initial_zero_base(self) -> None:
        self.assert_scope(self.base, self.base, {"smoke": False, "dashboard": False})

    def test_github_output_is_optional_and_stdout_is_json(self) -> None:
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(SCRIPT), "--base", self.base, "--head", self.base],
            cwd=self.repository, env=self.environment, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"smoke": False, "dashboard": False})
        self.assertFalse((self.root / "github-output").exists())

    def test_github_outputs_append_without_overwriting_other_step_outputs(self) -> None:
        output = self.root / "github-output"
        output.write_text("existing=reviewed\n")
        self.assert_scope(self.base, self.base, {"smoke": False, "dashboard": False})
        self.assertEqual(output.read_text(), "existing=reviewed\nsmoke=false\ndashboard=false\n")

    def test_submodule_config_cannot_hide_dashboard_changes(self) -> None:
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},theme-module")
        self.git("commit", "-m", "submodule fixture")
        self.git("config", "diff.ignoreSubmodules", "all")
        self.assert_scope(self.base, self.git("rev-parse", "HEAD"), {"smoke": False, "dashboard": True})

    def test_invalid_missing_and_non_commit_revisions_fail_without_outputs(self) -> None:
        tree = self.git("rev-parse", "HEAD^{tree}")
        blob = self.git("rev-parse", "HEAD:README.md")
        self.git("tag", "-a", "fixture-tag", "-m", "annotated")
        tag = self.git("rev-parse", "fixture-tag")
        revisions = ("0" * 40, "f" * 40, "HEAD", self.base[:12], self.base.upper(),
                     self.base + "\n", "--all", tree, blob, tag)
        for revision in revisions:
            for base, head in ((revision, self.base), (self.base, revision)):
                with self.subTest(base=base, head=head):
                    result = self.invoke(base, head)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertTrue(result.stderr)
                    self.assertFalse((self.root / "github-output").exists())

    def test_divergent_base_and_force_push_fail_closed(self) -> None:
        self.write("main-change.md")
        main = self.commit()
        self.git("checkout", "-b", "divergent", self.base)
        self.write("branch-change.md")
        head = self.commit()
        for base, candidate in ((main, head), (main, self.base)):
            result = self.invoke(base, candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / "github-output").exists())

    def test_merge_commit_diff_excludes_already_merged_main_changes(self) -> None:
        self.git("checkout", "-b", "smoke-fix")
        self.write(".github/workflows/test-nginx.yml")
        self.commit()
        self.git("checkout", "main")
        self.write("data/previously-merged.json")
        base = self.commit()
        self.git("merge", "--no-ff", "smoke-fix", "-m", "merge fixture")
        self.assert_scope(base, self.git("rev-parse", "HEAD"), {"smoke": True, "dashboard": False})

    def test_subdirectory_and_relative_diff_config_cannot_hide_changes(self) -> None:
        self.write(".github/workflows/test-nginx.yml")
        head = self.commit()
        nested = self.repository / "empty"
        nested.mkdir()
        self.git("config", "diff.relative", "true")
        result = self.invoke(self.base, head, cwd=nested)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"smoke": True, "dashboard": False})

    def test_git_replacement_cannot_hide_a_smoke_change(self) -> None:
        self.write(".github/workflows/test-nginx.yml")
        head = self.commit()
        self.git("replace", head, self.base)
        self.assert_scope(self.base, head, {"smoke": True, "dashboard": False})

    def test_non_repository_fails_without_outputs(self) -> None:
        result = self.invoke(self.base, self.base, cwd=self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.root / "github-output").exists())

    def invoke_main_gate(self, *, deployed_sha: str | None = None, deployment_runs=None, **overrides: str) -> subprocess.CompletedProcess[str]:
        workflow = SCRIPT.parents[1] / "workflows/main.yml"
        step = workflow.read_text().split(
            "      - name: Route an authenticated main push or enabled manual run\n", 1
        )[1]
        block = step.split("        run: |\n", 1)[1]
        lines = []
        for line in block.splitlines():
            if line.strip() and not line.startswith("          "):
                break
            lines.append(line)
        self.write(".github/scripts/ci_change_scope.py", SCRIPT.read_text())
        fixtures = self.root / "api.json"
        fixtures.write_text(json.dumps(deployment_documents(
            deployment_runs if deployment_runs is not None else [deployment_run(sha=deployed_sha or self.base)]
        )))
        bin_directory = self.root / "bin"
        bin_directory.mkdir(exist_ok=True)
        gh = bin_directory / "gh"
        gh.write_text(
            "#!/usr/bin/env python3\nimport json, os, sys\n"
            "with open(os.environ['DEPLOYMENT_API_FIXTURE']) as source:\n"
            "    print(json.dumps(json.load(source)[sys.argv[-1]]))\n"
        )
        gh.chmod(0o755)
        head = self.git("rev-parse", "HEAD")
        environment = {
            **self.environment,
            "GITHUB_EVENT_NAME": "push", "GITHUB_REF_TYPE": "branch",
            "GITHUB_REF_NAME": "main", "DEFAULT_BRANCH": "main",
            "BEFORE_SHA": self.base, "AFTER_SHA": head, "GITHUB_SHA": head,
            "PRODUCTION_DEPLOYMENT_ENABLED": "false",
            "GH_TOKEN": "fixture-only", "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_RUN_ID": "999", "GITHUB_RUN_ATTEMPT": "1",
            "DEPLOYMENT_API_FIXTURE": str(fixtures),
            "PATH": str(bin_directory) + os.pathsep + self.environment["PATH"],
            "GITHUB_OUTPUT": str(self.root / "gate-output"),
            **overrides,
        }
        return subprocess.run(
            ["bash", "-c", textwrap.dedent("\n".join(lines))],
            cwd=self.repository, env=environment, capture_output=True, text=True,
        )

    def test_main_dashboard_push_routes_without_enabling_manual_gate(self) -> None:
        self.write("content/linux/opensource_packages/nginx.md")
        self.commit()
        result = self.invoke_main_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.root / "gate-output").read_text()
        self.assertIn("dashboard=true\n", output)
        self.assertIn("smoke=false\n", output)

    def test_main_smoke_only_push_does_not_request_deployment(self) -> None:
        self.write(".github/workflows/test-nginx.yml")
        self.commit()
        result = self.invoke_main_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.root / "gate-output").read_text()
        self.assertIn("dashboard=false\n", output)
        self.assertIn("smoke=true\n", output)

    def test_smoke_push_catches_up_an_earlier_unpublished_dashboard_merge(self):
        self.write("content/linux/category.md")
        category_commit = self.commit()
        self.write(".github/workflows/test-nginx.yml")
        self.commit()
        result = self.invoke_main_gate(BEFORE_SHA=category_commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (self.root / "gate-output").read_text()
        self.assertIn("dashboard=true\n", output)
        self.assertIn("smoke=true\n", output)
        self.assertEqual(json.loads(result.stdout)["deployment_receipt"]["sha"], self.base)

    def test_smoke_push_skips_when_previous_dashboard_merge_is_already_deployed(self):
        self.write("content/linux/category.md")
        category_commit = self.commit()
        self.write(".github/workflows/test-nginx.yml")
        self.commit()
        result = self.invoke_main_gate(deployed_sha=category_commit, BEFORE_SHA=category_commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dashboard=false\n", (self.root / "gate-output").read_text())

    def test_content_reversion_after_partial_failed_deploy_still_deploys(self):
        self.write("README.md", "partially deployed B\n")
        intermediate = self.commit()
        self.write("README.md", "initial\n")
        restored = self.commit()
        self.assertEqual(self.git("diff", "--name-only", self.base, restored), "")
        partial = deployment_run(102, sha=intermediate)
        partial.update(conclusion="failure")
        current = deployment_run(999, sha=restored, attempt=1)
        current.update(status="in_progress", conclusion=None)
        result = self.invoke_main_gate(
            BEFORE_SHA=intermediate,
            deployment_runs=[current, partial, deployment_run(sha=self.base)],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dashboard=true\n", (self.root / "gate-output").read_text())
        self.assertTrue(json.loads(result.stdout)["deployment_receipt"]["requires_catch_up"])

    def test_current_scope_run_in_listing_does_not_deploy_an_unchanged_site(self):
        self.write(".github/workflows/test-nginx.yml")
        head = self.commit()
        current = deployment_run(999, sha=head, attempt=1)
        current.update(status="in_progress", conclusion=None)
        result = self.invoke_main_gate(deployment_runs=[current, deployment_run(sha=self.base)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dashboard=false\n", (self.root / "gate-output").read_text())

    def test_unrelated_deployed_commit_fails_without_routing_outputs(self):
        self.git("checkout", "-b", "other")
        self.write("other.md")
        unrelated = self.commit()
        self.git("checkout", "main")
        self.write(".github/workflows/test-nginx.yml")
        self.commit()
        result = self.invoke_main_gate(deployed_sha=unrelated)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.root / "gate-output").exists())

    def test_main_push_rejects_wrong_event_commit_branch_and_initial_base(self) -> None:
        self.write("content/linux/example.md")
        self.commit()
        for overrides in (
            {"AFTER_SHA": self.base}, {"GITHUB_SHA": self.base},
            {"GITHUB_REF_NAME": "production"}, {"GITHUB_REF_TYPE": "tag"},
            {"DEFAULT_BRANCH": "other"}, {"BEFORE_SHA": "0" * 40},
            {"GITHUB_EVENT_NAME": "pull_request"},
        ):
            with self.subTest(overrides=overrides):
                result = self.invoke_main_gate(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "gate-output").exists())

    def test_manual_main_dispatch_still_requires_exact_activation(self) -> None:
        for flag in ("false", "", "True", "1"):
            with self.subTest(flag=flag):
                result = self.invoke_main_gate(
                    GITHUB_EVENT_NAME="workflow_dispatch", PRODUCTION_DEPLOYMENT_ENABLED=flag
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "gate-output").exists())
        result = self.invoke_main_gate(
            GITHUB_EVENT_NAME="workflow_dispatch", PRODUCTION_DEPLOYMENT_ENABLED="true"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dashboard=true\n", (self.root / "gate-output").read_text())


if __name__ == "__main__":
    unittest.main()
