"""Cumulative context expansion consumes verified fleet identities, not model text."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import smoke_repair_cycle_context as context
import exact_run_aggregation as exact
from orchestration_contract import expected_run_name

REPOSITORY = context.REPOSITORY
BASE = "a" * 40
CANDIDATE = "b" * 40
TIME = "2026-09-24T12:00:00Z"
DESCRIPTOR = {"schema_version": 1, "repository": REPOSITORY, "base_sha": BASE,
    "candidate_sha": CANDIDATE, "cycle_id": "123456-1", "iteration": 1,
    "branch": "automation/smoke-repair-cycle/123456-1/iteration-1"}


class Fixture:
    def __init__(self, slugs=("alpha", "bravo", "charlie")):
        self.sources = {slug: f"name: Trusted original {slug}\n" for slug in slugs}
        self.registrations = tuple(exact.PackageRegistration(f"test-{slug}", f"test-{slug}",
            f".github/workflows/test-{slug}.yml", slug) for slug in slugs)
        self.batch = exact.BatchDefinition(1, ".github/workflows/test-all-packages-batch1.yml",
            "Test All Packages (Batch 1) on Arm64", "batch1-test-results", self.registrations, (), ())
        self.topology = (self.batch,)
        original = self.original("alpha")
        self.admission = {"schema_version": 1, "request": {
            "schema_version": 2, "repository": REPOSITORY, "base_sha": BASE,
            "orchestrator_run_id": 123456, "orchestrator_attempt": 1, "context_artifact_id": 777,
            "cycle_id": "123456-1", "iteration": 1, "previous_feedback_run_id": None,
            "previous_feedback_artifact_id": None, "proposals": [self.proposal(original)]},
            "repairs": [{"context": original, "proposal": {}}]}
        self.runs, self.jobs = {}, {}
        history = [self.entry(100, {"bravo"}), self.entry(101, {"bravo"})]
        self.receipt = {"schema_version": 1, "kind": "smoke-repair-candidate-fleet",
            "descriptor": deepcopy(DESCRIPTOR), "status": "failure", "publishing": False,
            "topology_sha256": "c" * 64, "started_at": TIME, "completed_at": TIME,
            "history": [history], "manifest": {}, "attestation": {}, "summary": {}}
        self.refresh_summary()
        self.api = Mock()
        self.api.api.side_effect = self.read

    @staticmethod
    def proposal(original):
        return {"package_slug": original["package_slug"], "context_sha256": context.context_digest(original),
            "operations": [{"kind": "prepend_apt", "step": 2, "packages": ["libfuse3-dev"]}]}

    def original(self, slug):
        return {"repository": REPOSITORY, "base_sha": BASE, "orchestration_id": "orchestration-123456-1",
            "orchestrator_run_id": 123456, "orchestrator_run_attempt": 1, "package_slug": slug,
            "workflow_path": f".github/workflows/test-{slug}.yml", "called_job": f"test-{slug}",
            "source_text": self.sources[slug], "failed_steps": ["Original failed install"],
            "log_excerpt": "Previously authenticated original diagnostic", "batch": 1,
            "initial_run_id": 1, "confirmation_run_id": 2, "confirmation_job_id": 3}

    def entry(self, run_id, failed):
        nonce = f"{run_id:064x}"
        state = "failure" if failed else "success"
        self.runs[run_id] = {"id": run_id, "run_attempt": 1, "name": self.batch.workflow_name,
            "path": self.batch.workflow_path, "display_title": expected_run_name(1, "orchestration-123456-1", nonce),
            "event": "workflow_dispatch", "head_branch": DESCRIPTOR["branch"], "head_sha": CANDIDATE,
            "status": "completed", "conclusion": state,
            "repository": {"full_name": REPOSITORY}, "head_repository": {"full_name": REPOSITORY}}
        observations, jobs = [], []
        for index, registration in enumerate(self.registrations):
            slug = registration.package_slug
            job_id = 10 * run_id + index
            job_state = "failure" if slug in failed else "success"
            job_url = f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/job/{job_id}"
            steps = [{"number": n + 2, "name": f"Test {n + 1} - native probe",
                      "status": "completed", "conclusion": "failure" if slug in failed and n == 1 else "success",
                      "started_at": TIME, "completed_at": TIME} for n in range(5)]
            steps.append({"number": 7, "name": "Enforce failure status", "status": "completed",
                          "conclusion": job_state, "started_at": TIME, "completed_at": TIME})
            normalized_job = {"id": job_id, "run_id": run_id, "run_attempt": 1,
                              "name": exact.expected_job_name(registration), "conclusion": job_state}
            jobs.append(normalized_job)
            observation = {"package_slug": slug, "workflow_path": registration.workflow_path,
                "batch": 1, "run_id": run_id, "run_attempt": 1, "job_id": job_id, "job_url": job_url,
                "status": job_state, "required_steps": [{k: step[k] for k in ("number", "name", "conclusion")} for step in steps]}
            observations.append(observation)
            self.jobs[job_id] = {**normalized_job, "head_sha": CANDIDATE, "head_branch": DESCRIPTOR["branch"],
                "status": "completed", "labels": ["ubuntu-24.04-arm"], "runner_group_id": 0,
                "runner_group_name": "GitHub Actions", "runner_id": 45, "runner_name": "Hosted Agent",
                "html_url": job_url, "url": f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{job_id}",
                "run_url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}",
                "started_at": TIME, "completed_at": TIME, "steps": steps}
        return {"batch": 1, "run_id": run_id, "run_attempt": 1, "dispatch_nonce": nonce,
            "status": state, "artifact_status": "verified", "observations": observations,
            "record": {"run": {"id": run_id, "attempt": 1, "head_sha": CANDIDATE,
                "head_branch": DESCRIPTOR["branch"], "conclusion": state}, "jobs": jobs}}

    def refresh_summary(self):
        final = self.receipt["history"][0][-1]
        failed = [item for item in final["observations"] if item["status"] == "failure"]
        self.receipt["status"] = final["status"]
        self.receipt["summary"] = {"kind": "candidate-global-summary", "publishing": False,
            "status": final["status"], "evidence_status": "complete", "candidate_sha": CANDIDATE,
            "batch_count": 1, "package_count": len(self.registrations),
            "passed_packages": len(self.registrations) - len(failed), "failed_packages": deepcopy(failed),
            "failed_batches": [1] if final["status"] == "failure" else [],
            "accepted_runs": [{"batch": 1, "run_id": final["run_id"], "run_attempt": 1, "status": final["status"]}]}

    def read(self, endpoint):
        if "/git/ref/heads/" in endpoint:
            branch = endpoint.split("/git/ref/heads/")[1]
            return {"ref": f"refs/heads/{branch}", "object": {"type": "commit",
                "sha": BASE if branch == "main" else CANDIDATE}}
        if "/actions/runs/" in endpoint:
            return deepcopy(self.runs[int(endpoint.rsplit("/", 1)[-1])])
        if "/actions/jobs/" in endpoint:
            return deepcopy(self.jobs[int(endpoint.rsplit("/", 1)[-1])])
        raise AssertionError(endpoint)


class ContextExpansionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.root = Path("/trusted/main")
        self.topology = patch.object(context, "discover_topology_at_commit", side_effect=lambda *_: self.fixture.topology).start()
        self.source = patch.object(context, "read_source", side_effect=lambda root, sha, path:
            self.fixture.sources[Path(path).stem.removeprefix("test-")]).start()
        self.addCleanup(patch.stopall)

    def expand(self):
        return context.expand_contexts(self.fixture.admission, self.fixture.receipt, self.root, self.fixture.api)

    def test_retains_original_and_adds_only_confirmed_new_failure(self):
        original = deepcopy(self.fixture.admission["repairs"][0]["context"])
        before_admission, before_receipt = deepcopy(self.fixture.admission), deepcopy(self.fixture.receipt)
        result = self.expand()
        self.assertEqual([row["package_slug"] for row in result], ["alpha", "bravo"])
        self.assertEqual(result[0], original)
        self.assertEqual(context.context_digest(result[0]), context.context_digest(original))
        added = result[1]
        self.assertEqual(set(added), context.CONTEXT_KEYS)
        self.assertEqual(added["source_text"], self.fixture.sources["bravo"])
        self.assertEqual(added["base_sha"], BASE)
        self.assertEqual((added["initial_run_id"], added["confirmation_run_id"], added["confirmation_job_id"]), (100, 101, 1011))
        self.assertEqual(added["failed_steps"], ["Test 2 - native probe", "Enforce failure status"])
        self.assertEqual(added["log_excerpt"], "Log unavailable.")
        self.assertEqual(self.fixture.admission, before_admission)
        self.assertEqual(self.fixture.receipt, before_receipt)
        self.assertEqual(self.expand(), result)
        self.assertTrue(all(call.args[1] == BASE for call in self.source.call_args_list))
        self.assertFalse(any("/logs" in c.args[0] for c in self.fixture.api.api.call_args_list))

    def test_success_returns_original_contexts_without_live_job_reads(self):
        self.fixture.receipt["history"] = [[self.fixture.entry(110, set())]]
        self.fixture.refresh_summary()
        self.assertEqual(self.expand(), [self.fixture.admission["repairs"][0]["context"]])
        self.assertTrue(all("/git/ref/heads/" in c.args[0] for c in self.fixture.api.api.call_args_list))

    def test_existing_failed_context_stays_unchanged_instead_of_rebinding(self):
        original = self.fixture.original("bravo")
        self.fixture.admission["repairs"].append({"context": original, "proposal": {}})
        self.fixture.admission["request"]["proposals"].append(self.fixture.proposal(original))
        result = self.expand()
        self.assertEqual(result[1], original)
        self.assertEqual(result[1]["confirmation_run_id"], 2)
        self.assertTrue(all("/git/ref/heads/" in c.args[0] for c in self.fixture.api.api.call_args_list))

    def test_changed_original_source_is_rejected_not_trusted_or_rewritten(self):
        original = self.fixture.admission["repairs"][0]["context"]
        original["source_text"] = "model-supplied candidate source"
        self.fixture.admission["request"]["proposals"][0]["context_sha256"] = context.context_digest(original)
        with self.assertRaisesRegex(context.ContractError, "original context source"):
            self.expand()

    def test_missing_confirmation_is_honest_blocker(self):
        self.fixture.receipt["history"][0].pop(0)
        self.fixture.refresh_summary()
        with self.assertRaisesRegex(context.ContractError, "no distinct confirmation"):
            self.expand()

    def test_new_failure_only_in_second_run_is_not_eligible(self):
        self.fixture.receipt["history"][0][0] = self.fixture.entry(100, {"alpha"})
        with self.assertRaisesRegex(context.ContractError, "not reproduced"):
            self.expand()

    def test_duplicate_original_context_and_digest_substitution_rejected(self):
        self.fixture.admission["repairs"].append(deepcopy(self.fixture.admission["repairs"][0]))
        with self.assertRaises(context.ContractError):
            self.expand()
        self.fixture.admission["repairs"].pop()
        self.fixture.admission["request"]["proposals"][0]["context_sha256"] = "0" * 64
        with self.assertRaisesRegex(context.ContractError, "context digest"):
            self.expand()

    def test_all_original_contexts_sorted_without_losing_resolved_package(self):
        charlie = self.fixture.original("charlie")
        self.fixture.admission["repairs"].insert(0, {"context": charlie, "proposal": {}})
        self.fixture.admission["request"]["proposals"].append(self.fixture.proposal(charlie))
        result = self.expand()
        self.assertEqual([row["package_slug"] for row in result], ["alpha", "bravo", "charlie"])
        self.assertEqual(result[2], charlie)

    def test_context_budget_is_cumulative_and_before_job_reads(self):
        self.fixture = Fixture(("alpha",) + tuple(f"package-{n}" for n in range(10)))
        failed = {p.package_slug for p in self.fixture.registrations if p.package_slug != "alpha"}
        self.fixture.receipt["history"] = [[self.fixture.entry(100, failed), self.fixture.entry(102, failed)]]
        self.fixture.refresh_summary()
        with self.assertRaisesRegex(context.ContractError, "ten-package"):
            self.expand()
        self.assertTrue(all("/git/ref/heads/" in c.args[0] for c in self.fixture.api.api.call_args_list))

    def test_exactly_ten_cumulative_contexts_are_supported(self):
        self.fixture = Fixture(("alpha",) + tuple(f"package-{n}" for n in range(9)))
        failed = {p.package_slug for p in self.fixture.registrations if p.package_slug != "alpha"}
        self.fixture.receipt["history"] = [[self.fixture.entry(100, failed), self.fixture.entry(101, failed)]]
        self.fixture.refresh_summary()
        result = self.expand()
        self.assertEqual(len(result), 10)
        self.assertEqual(result[0], self.fixture.admission["repairs"][0]["context"])
        self.assertTrue(all(row["log_excerpt"] == "Log unavailable." for row in result[1:]))

    def test_second_iteration_preserves_previously_expanded_context_digest(self):
        expanded = self.expand()
        self.fixture.admission["repairs"] = [{"context": row, "proposal": {}} for row in expanded]
        self.fixture.admission["request"].update(iteration=2, previous_feedback_run_id=800, previous_feedback_artifact_id=900,
            proposals=[self.fixture.proposal(row) for row in expanded])
        self.fixture.receipt["descriptor"].update(iteration=2,
            branch="automation/smoke-repair-cycle/123456-1/iteration-2")
        for entry in self.fixture.receipt["history"][0]:
            entry["record"]["run"]["head_branch"] = self.fixture.receipt["descriptor"]["branch"]
        self.fixture.api.reset_mock()
        result = self.expand()
        self.assertEqual(result, expanded)
        self.assertEqual([context.context_digest(row) for row in result],
                         [context.context_digest(row) for row in expanded])
        self.assertTrue(all("/git/ref/heads/" in c.args[0] for c in self.fixture.api.api.call_args_list))

    def test_live_job_binding_failures_cannot_create_context(self):
        original = deepcopy(self.fixture.jobs[1011])
        for field, value in (("id", 1), ("run_id", 100), ("run_attempt", 2), ("head_sha", BASE),
                             ("head_branch", "main"), ("name", "other job"), ("conclusion", "success"),
                             ("labels", ["self-hosted"]), ("runner_group_id", 3),
                             ("html_url", "https://invalid.example"), ("runner_id", 0)):
            with self.subTest(field=field):
                self.fixture.jobs[1011] = {**original, field: value}
                with self.assertRaises(context.ContractError):
                    self.expand()
        self.fixture.jobs[1011] = original

    def test_live_run_binding_failures_cannot_create_context(self):
        original = deepcopy(self.fixture.runs[101])
        for field, value in (("id", 100), ("run_attempt", 2), ("head_sha", BASE), ("head_branch", "main"),
                             ("event", "push"), ("status", "in_progress"), ("conclusion", "success"),
                             ("head_repository", {"full_name": "other/repository"}), ("display_title", "spoofed")):
            with self.subTest(field=field):
                self.fixture.runs[101] = {**original, field: value}
                with self.assertRaises(context.ContractError):
                    self.expand()
        self.fixture.runs[101] = original

    def test_required_probe_drift_fails_closed(self):
        self.fixture.jobs[1011]["steps"][1]["conclusion"] = "success"
        with self.assertRaisesRegex(context.ContractError, "probes changed"):
            self.expand()

    def test_main_or_candidate_advancing_during_reads_is_rejected(self):
        original_read = self.fixture.read
        for branch in ("main", DESCRIPTOR["branch"]):
            with self.subTest(branch=branch):
                calls = []
                def read(endpoint):
                    value = original_read(endpoint)
                    calls.append(endpoint)
                    if endpoint.endswith("/git/ref/heads/" + branch) and any("/actions/jobs/" in p for p in calls):
                        value["object"]["sha"] = "f" * 40
                    return value
                self.fixture.api.api.side_effect = read
                with self.assertRaises(context.ContractError):
                    self.expand()

    def test_run_attempt_advance_after_job_read_is_rejected(self):
        original_read = self.fixture.read
        calls = []
        def read(endpoint):
            value = original_read(endpoint)
            calls.append(endpoint)
            if endpoint.endswith("/actions/runs/101") and any("/actions/jobs/1011" in p for p in calls):
                value["run_attempt"] = 2
            return value
        self.fixture.api.api.side_effect = read
        with self.assertRaises(context.ContractError):
            self.expand()

    def test_summary_cannot_hide_or_invent_failed_packages(self):
        original = deepcopy(self.fixture.receipt)
        changes = (lambda r: r["summary"].update(failed_packages=[]),
                   lambda r: r["summary"].update(package_count=1),
                   lambda r: r["summary"].update(evidence_status="incomplete"),
                   lambda r: r.update(status="success"),
                   lambda r: r.update(publishing=True),
                   lambda r: r["history"].append(deepcopy(r["history"][0])),
                   lambda r: r["history"][0][-1]["observations"].pop())
        for change in changes:
            with self.subTest(change=change):
                self.fixture.receipt = deepcopy(original)
                change(self.fixture.receipt)
                with self.assertRaises(context.ContractError):
                    self.expand()

    def test_extra_private_fields_and_wrong_cycle_rejected(self):
        original = deepcopy(self.fixture.receipt)
        for change in (lambda r: r.update(model_token="private"),
                       lambda r: r["descriptor"].update(iteration=2),
                       lambda r: r["descriptor"].update(base_sha="e" * 40),
                       lambda r: r["history"][0][-1]["observations"][1].update(source_text="untrusted")):
            with self.subTest(change=change):
                self.fixture.receipt = deepcopy(original)
                change(self.fixture.receipt)
                with self.assertRaises(context.ContractError):
                    self.expand()

    def test_live_api_private_metadata_and_logs_never_enter_context(self):
        self.fixture.jobs[1011]["private_model_metadata"] = "not-for-export"
        result = self.expand()
        self.assertNotIn("not-for-export", str(result))
        self.assertEqual(result[-1]["log_excerpt"], "Log unavailable.")


class FleetContextIntegrationTests(unittest.TestCase):
    """Exercise the actual fleet worker/verifier, mocking only GitHub and Git."""

    def setUp(self):
        import test_smoke_repair_fleet as worker_tests
        self.worker_tests = worker_tests
        self.fixture = worker_tests.FleetTests("test_all_registered_batches_green_real_artifact_verifiers")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.descriptor = worker_tests.DESCRIPTOR
        registration = self.fixture.topology[0].packages[0]
        original = {"repository": REPOSITORY, "base_sha": BASE, "orchestration_id": "orchestration-9000-1",
            "orchestrator_run_id": 9000, "orchestrator_run_attempt": 1,
            "package_slug": registration.package_slug, "workflow_path": registration.workflow_path,
            "called_job": registration.called_job,
            "source_text": (self.fixture.root / registration.workflow_path).read_text(),
            "failed_steps": ["Original failed install"], "log_excerpt": "Authenticated original log.",
            "batch": 1, "initial_run_id": 1, "confirmation_run_id": 2, "confirmation_job_id": 3}
        self.admission = {"schema_version": 1, "request": {
            "schema_version": 2, "repository": REPOSITORY, "base_sha": BASE,
            "orchestrator_run_id": 9000, "orchestrator_attempt": 1, "context_artifact_id": 777,
            "cycle_id": "9000-1", "iteration": 1, "previous_feedback_run_id": None,
            "previous_feedback_artifact_id": None, "proposals": [Fixture.proposal(original)]},
            "repairs": [{"context": original, "proposal": {}}]}
        source = patch.object(context, "read_source", side_effect=lambda root, sha, path: (root / path).read_text())
        source.start()
        self.addCleanup(source.stop)
        topology = patch.object(context, "discover_topology_at_commit", return_value=self.fixture.topology)
        topology.start()
        self.addCleanup(topology.stop)

    def expanded(self, receipt):
        verified = self.fixture.worker().verify(self.descriptor, receipt, **self.fixture.options)
        return context.expand_contexts(self.admission, verified, self.fixture.root, self.fixture.api)

    def initial_unavailable(self, run_id, *, collector=False):
        def mutate(endpoint, value):
            if collector and endpoint.endswith("/dispatches") and run_id in self.fixture.api.runs:
                self.fixture.api.runs[run_id]["conclusion"] = "failure"
                summary = self.fixture.api.jobs[10 * run_id + 1]
                summary["conclusion"] = "failure"
                for index, step in enumerate(summary["steps"]):
                    step["conclusion"] = "failure" if index == 0 else "skipped"
            if f"/actions/runs/{run_id}/artifacts?" in endpoint:
                return {"total_count": 0, "artifacts": []}
            return value
        self.fixture.api.mutate = mutate

    def test_actual_fleet_missing_initial_artifact_recovers_and_expands(self):
        self.fixture.api.failures = {1: [True, False]}
        self.initial_unavailable(1000)
        receipt = self.fixture.run_fleet()
        self.assertEqual(receipt["status"], "success")
        self.assertEqual(receipt["summary"]["evidence_status"], "complete")
        initial, confirmation = receipt["history"][0]
        self.assertEqual(initial["artifact_status"], "missing")
        self.assertIsNone(initial["record"])
        self.assertEqual(initial["observations"][0]["status"], "failure")
        self.assertEqual(confirmation["artifact_status"], "verified")
        self.assertEqual(self.expanded(receipt), [self.admission["repairs"][0]["context"]])

    def test_actual_fleet_collector_only_failure_recovers_and_expands(self):
        self.initial_unavailable(1000, collector=True)
        receipt = self.fixture.run_fleet()
        initial, confirmation = receipt["history"][0]
        self.assertEqual(initial["artifact_status"], "collector_failed")
        self.assertIsNone(initial["record"])
        self.assertEqual(initial["observations"][0]["status"], "success")
        self.assertEqual(confirmation["artifact_status"], "verified")
        self.assertEqual(receipt["summary"]["failed_packages"], [])
        self.assertEqual(self.expanded(receipt), [self.admission["repairs"][0]["context"]])

    def test_actual_fleet_cannot_expand_persistent_failure_with_incomplete_initial_artifact(self):
        self.fixture.api.failures = {2: [True, True]}
        self.initial_unavailable(1001)
        receipt = self.fixture.run_fleet()
        self.assertEqual(receipt["status"], "failure")
        self.assertEqual(receipt["summary"]["evidence_status"], "complete")
        with self.assertRaisesRegex(context.ContractError, "incomplete initial artifact"):
            self.expanded(receipt)

    def test_recovered_collector_does_not_block_separate_fully_confirmed_package(self):
        self.fixture.api.failures = {2: [True, True]}
        self.initial_unavailable(1000, collector=True)
        receipt = self.fixture.run_fleet()
        result = self.expanded(receipt)
        self.assertEqual([row["package_slug"] for row in result], ["alpha", "bravo"])
        self.assertEqual(result[0], self.admission["repairs"][0]["context"])
        self.assertEqual(result[1]["log_excerpt"], "Log unavailable.")

    def test_selected_missing_artifact_never_produces_an_admissible_receipt(self):
        self.fixture.api.failures = {1: [True, True]}
        self.initial_unavailable(1002)
        with self.assertRaisesRegex(context.ContractError, "selected fleet evidence is incomplete"):
            self.fixture.run_fleet()


if __name__ == "__main__":
    unittest.main()
