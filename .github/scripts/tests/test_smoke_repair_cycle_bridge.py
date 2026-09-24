"""Multi-package callbacks cannot authorize their own evidence or readiness."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_repair_cycle_bridge as cycle
import test_smoke_repair_bridge as legacy
from test_smoke_repair_pipeline import context


def payload():
    old = legacy.payload()
    return {"schema_version": 2, "repository": old["repository"], "base_sha": old["base_sha"],
            "orchestrator_run_id": old["orchestrator_run_id"], "orchestrator_attempt": 1,
            "context_artifact_id": old["context_artifact_id"], "cycle_id": "123456-1", "iteration": 1,
            "previous_feedback_run_id": None, "previous_feedback_artifact_id": None,
            "proposals": [{key: old[key] for key in ("package_slug", "context_sha256", "operations")}]}


class CycleEventTests(unittest.TestCase):
    def test_exact_bot_on_cycle_workflow_and_no_legacy_sender_substitution(self):
        event, environment = legacy.event(), legacy.environment()
        event.update(action=cycle.EVENT, client_payload={"repair": payload()})
        environment["GITHUB_WORKFLOW_REF"] = f"{cycle.REPOSITORY}/{cycle.WORKFLOW}@refs/heads/main"
        self.assertEqual(cycle.validate_event(event, environment), payload())
        for key in environment:
            with self.subTest(key=key):
                broken = dict(environment)
                del broken[key]
                with self.assertRaises(ValueError):
                    cycle.validate_event(event, broken)
        with self.assertRaises(ValueError):
            cycle.validate_event(event, legacy.environment())

    def test_dispatch_transport_is_one_bounded_field_with_no_extra_public_output(self):
        event, environment = legacy.event(), legacy.environment()
        environment["GITHUB_WORKFLOW_REF"] = f"{cycle.REPOSITORY}/{cycle.WORKFLOW}@refs/heads/main"
        transport = {"repair": payload()}
        self.assertLessEqual(len(transport), 10)
        self.assertLess(len(cycle.canonical(transport).encode("utf-8")), 65535)
        for invalid in (None, [], {}, payload(), {"payload": payload()},
                        {**transport, "diagnosis": "private model output"}):
            event.update(action=cycle.EVENT, client_payload=invalid)
            with self.subTest(transport=invalid), self.assertRaises(ValueError):
                cycle.validate_event(event, environment)

    def test_iteration_requires_exact_previous_public_feedback_pointers(self):
        for iteration in (2, 3):
            value = payload()
            value.update(iteration=iteration, previous_feedback_run_id=501, previous_feedback_artifact_id=601)
            self.assertEqual(cycle.validate_payload(value, value["base_sha"]), value)
            for field in ("previous_feedback_run_id", "previous_feedback_artifact_id"):
                for invalid in (None, True, 0, -1, "501"):
                    with self.subTest(iteration=iteration, field=field, invalid=invalid):
                        broken = deepcopy(value)
                        broken[field] = invalid
                        with self.assertRaises(ValueError):
                            cycle.validate_payload(broken, broken["base_sha"])

    def test_private_fields_wrong_identity_and_budget_overruns_rejected(self):
        changes = [
            {"schema_version": True}, {"repository": "private/project"}, {"base_sha": "b" * 40},
            {"orchestrator_run_id": True}, {"orchestrator_attempt": 2}, {"context_artifact_id": 0},
            {"cycle_id": "../123456-1"}, {"iteration": 0}, {"iteration": 4}, {"iteration": True},
            {"previous_feedback_run_id": 1}, {"previous_feedback_artifact_id": 2},
            {"proposals": []}, {"proposals": payload()["proposals"] * 11},
            {"diagnosis": "private model text"}, {"internal_run_id": 1234},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                cycle.validate_payload({**payload(), **change}, "a" * 40)
        for change in ({"context_sha256": "x"}, {"package_slug": "../../main"},
                       {"ready": True}, {"operations": []}, {"source": "echo pass"}):
            value = payload()
            value["proposals"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                cycle.validate_payload(value, value["base_sha"])

    def test_complete_unique_sorted_inventory(self):
        value = payload()
        other = {**value["proposals"][0], "package_slug": "zebra-package"}
        value["proposals"].append(other)
        self.assertEqual(cycle.validate_payload(value, value["base_sha"]), value)
        for rows in (value["proposals"][::-1], value["proposals"] + [other]):
            with self.assertRaises(ValueError):
                cycle.validate_payload({**value, "proposals": rows}, value["base_sha"])


class CycleAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.value = payload()
        self.context = context()
        self.value["proposals"][0]["context_sha256"] = cycle.context_digest(self.context)
        self.api = Mock()
        self.api.api.side_effect = lambda endpoint: (
            {"ref": "refs/heads/main", "object": {"type": "commit", "sha": self.value["base_sha"]}}
            if endpoint.endswith("/git/ref/heads/main") else [])
        self.auth = patch.object(cycle, "authenticate_contexts", return_value=[self.context]).start()
        self.addCleanup(patch.stopall)

    def admit(self, previous=None):
        return cycle.admit_cycle(self.value, self.api, Path.cwd(), now=1, verify_previous=previous)

    def test_one_complete_incident_passes_original_public_policy(self):
        result = self.admit()
        self.assertEqual(len(result["repairs"]), 1)
        self.assertIn("libfuse3-dev", result["repairs"][0]["proposal"]["edits"][0]["new"])
        self.assertEqual(result["request"], self.value)

    def test_partial_incident_or_changed_context_cannot_stage(self):
        self.auth.return_value.append({**self.context, "package_slug": "another-package"})
        with self.assertRaises(ValueError):
            self.admit()
        self.auth.return_value = [self.context]
        self.value["proposals"][0]["context_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            self.admit()

    def test_next_iteration_needs_live_failed_previous_candidate_not_model_assertion(self):
        self.value.update(iteration=2, previous_feedback_run_id=501, previous_feedback_artifact_id=601)
        with self.assertRaises(ValueError):
            self.admit()
        previous = {"status": "failed", "cycle_id": self.value["cycle_id"], "base_sha": self.value["base_sha"],
                    "iteration": 1, "proposal_digest": "e" * 64}
        verifier = Mock(return_value=previous)
        self.admit(verifier)
        verifier.assert_called_once()
        for change in ({"status": "passed"}, {"status": "incomplete"}, {"iteration": True},
                       {"iteration": 2}, {"cycle_id": "123457-1"}, {"base_sha": "b" * 40},
                       {"proposal_digest": cycle.proposal_digest(self.value["proposals"])}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.admit(Mock(return_value={**previous, **change}))

    def test_existing_branch_or_old_pr_is_never_overwritten(self):
        branch = cycle.candidate_branch(self.value["cycle_id"], 1)
        self.api.api.return_value = None
        for evidence in ([{"ref": f"refs/heads/{branch}"}], {"not": "an inventory"}):
            self.api.api.side_effect = lambda endpoint: evidence
            with self.assertRaises(ValueError):
                self.admit()
        self.api.api.side_effect = lambda endpoint: [{"number": 12}] if "/pulls?" in endpoint else []
        with self.assertRaises(ValueError):
            self.admit()

    def test_readmission_rechecks_source_but_leaves_branch_identity_to_publisher(self):
        admission = self.admit()
        self.api.api.side_effect = lambda endpoint: (
            {"ref": "refs/heads/main", "object": {"type": "commit", "sha": self.value["base_sha"]}}
            if endpoint.endswith("/git/ref/heads/main") else [{"ref": "existing"}])
        result = cycle.revalidate_admission(admission, self.api, Path.cwd(), now=datetime.fromtimestamp(1, timezone.utc))
        self.assertEqual(result, admission)
        self.assertIsInstance(self.auth.call_args.kwargs["now"], float)
        changed = deepcopy(admission)
        changed["repairs"][0]["proposal"]["edits"][0]["new"] += "fake"
        with self.assertRaises(ValueError):
            cycle.revalidate_admission(changed, self.api, Path.cwd(), now=1)


class FeedbackArtifactTests(unittest.TestCase):
    def setUp(self):
        self.payload = payload()
        self.payload.update(iteration=2, previous_feedback_run_id=501, previous_feedback_artifact_id=601)
        self.now = datetime(2026, 9, 24, 10, tzinfo=timezone.utc).timestamp()
        self.run = {"id": 501, "run_attempt": 1, "event": "repository_dispatch", "head_branch": "main",
                    "head_sha": self.payload["base_sha"], "path": cycle.WORKFLOW,
                    "status": "completed", "conclusion": "failure", "created_at": "2026-09-24T08:00:00Z",
                    "repository": {"full_name": cycle.REPOSITORY}, "head_repository": {"full_name": cycle.REPOSITORY}}
        self.job = {"id": 701, "run_id": 501, "run_attempt": 1, "head_sha": self.payload["base_sha"],
                    "name": cycle.FEEDBACK_JOB, "status": "completed", "conclusion": "failure",
                    "started_at": "2026-09-24T08:10:00Z", "completed_at": "2026-09-24T09:00:00Z",
                    "steps": [{"name": name, "status": "completed", "conclusion": "success"}
                              for name in sorted(cycle.FEEDBACK_STEPS)]}
        self.artifact = {"id": 601, "name": "smoke-repair-cycle-feedback-123456-1-1",
                         "expired": False, "created_at": "2026-09-24T08:50:00Z",
                         "workflow_run": {"id": 501, "head_sha": self.payload["base_sha"], "head_branch": "main"}}
        self.document = {"untrusted": "data still needs live verification"}
        self.archive("feedback.json", json.dumps(self.document))
        self.api = Mock()
        self.api.api.side_effect = self.read
        patch.object(cycle, "complete_jobs", side_effect=lambda pages: pages).start()
        patch("smoke_repair_bridge.artifact_inventory", side_effect=lambda *_: [self.artifact]).start()
        self.addCleanup(patch.stopall)

    def archive(self, name, data, extra=False):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(name, data)
            if extra:
                archive.writestr("extra.json", "{}")
        self.raw = stream.getvalue()
        self.artifact.update(size_in_bytes=len(self.raw), digest="sha256:" + hashlib.sha256(self.raw).hexdigest())

    def read(self, endpoint, **options):
        if endpoint.endswith("/zip"):
            return self.raw
        if "/jobs?" in endpoint:
            return [deepcopy(self.job)]
        return deepcopy(self.run)

    def verify(self):
        return cycle.read_feedback_document(self.payload, self.api, now=self.now)

    def test_exact_public_producer_and_digest_allow_only_untrusted_document_read(self):
        self.assertEqual(self.verify(), self.document)

    def test_wrong_run_identity_state_and_freshness_rejected(self):
        original = deepcopy(self.run)
        for change in ({"id": True}, {"id": 502}, {"run_attempt": 2}, {"event": "workflow_dispatch"},
                       {"head_sha": "b" * 40}, {"head_branch": "production"}, {"path": "other.yml"},
                       {"conclusion": "success"}, {"status": "in_progress"},
                       {"repository": {"full_name": "other/repo"}}, {"created_at": "2026-09-20T08:00:00Z"}):
            self.run = {**original, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify()

    def test_failed_collection_and_wrong_job_identity_rejected(self):
        original = deepcopy(self.job)
        for change in ({"run_id": 502}, {"run_attempt": True}, {"head_sha": "b" * 40},
                       {"conclusion": "success"}, {"steps": []}, {"name": "untrusted producer"}):
            self.job = {**original, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify()
        self.job = deepcopy(original)
        self.job["steps"][0]["conclusion"] = "failure"
        with self.assertRaises(ValueError):
            self.verify()

    def test_corrupt_stale_or_unbound_artifact_rejected(self):
        original = deepcopy(self.artifact)
        for change in ({"id": 602}, {"expired": True}, {"digest": "sha256:" + "a" * 64},
                       {"size_in_bytes": 0}, {"name": "different"}, {"workflow_run": {"id": 502}},
                       {"created_at": "2026-09-24T09:01:00Z"}):
            self.artifact = {**original, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify()

    def test_zip_traversal_multiple_files_and_invalid_json_rejected(self):
        for name, data, extra in (("../feedback.json", "{}", False), ("feedback.json", "{}", True),
                                  ("feedback.json", "not-json", False)):
            self.archive(name, data, extra)
            with self.subTest(name=name, extra=extra), self.assertRaises(ValueError):
                self.verify()

    def test_rerun_during_artifact_read_rejected(self):
        def read(endpoint, **options):
            result = self.read(endpoint, **options)
            if endpoint.endswith("/zip"):
                self.run["run_attempt"] = 2
            return result
        self.api.api.side_effect = read
        with self.assertRaises(ValueError):
            self.verify()


if __name__ == "__main__":
    unittest.main()
