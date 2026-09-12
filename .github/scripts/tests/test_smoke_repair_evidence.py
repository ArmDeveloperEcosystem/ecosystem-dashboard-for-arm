from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_repair_evidence as evidence
import test_smoke_recovery as fixture


class EvidenceFixture:
    def __init__(self):
        self.manifest = fixture.initial_manifest()
        self.original = self.manifest["batches"][0]
        self.replacement = dict(self.original, run_id=20001, dispatch_nonce="f" * 64)
        self.audit = {"status": "failed", "original_manifest": self.manifest,
            "failed_batches": [1], "history": [
                {"batch": 1, "run_id": self.original["run_id"], "retry": 0, "classification": "failed"},
                {"batch": 1, "run_id": self.replacement["run_id"], "retry": 1, "classification": "failed"},
            ], "dispatches": [{"batch": 1, "run_id": self.replacement["run_id"],
                "dispatch_nonce": self.replacement["dispatch_nonce"], "retry": 1,
                "expected_sha": fixture.SHA, "run_attempt": 1,
                "reason": "failed_batch_confirmation", "status": "registered"}]}
        self.records = {record["run_id"]: record for record in (self.original, self.replacement)}
        self.responses = {}
        self.calls = []
        prefix = f"repos/{fixture.REPOSITORY}"
        self.responses[prefix] = {"full_name": fixture.REPOSITORY, "private": False}
        self.responses[f"{prefix}/git/ref/heads/main"] = fixture.branch_ref()
        self.parent = {"id": 123456, "run_attempt": 1, "head_sha": fixture.SHA,
            "head_branch": "main", "path": evidence.ORCHESTRATOR_PATH, "event": "schedule",
            "repository": {"full_name": fixture.REPOSITORY}, "head_repository": {"full_name": fixture.REPOSITORY}}
        self.job = {"id": 99, "run_id": 123456, "run_attempt": 1, "head_sha": fixture.SHA,
            "name": evidence.ORCHESTRATOR_JOB, "status": "completed", "conclusion": "failure",
            "html_url": f"https://github.com/{fixture.REPOSITORY}/actions/runs/123456/job/99",
            "started_at": fixture.STARTED, "completed_at": fixture.COMPLETED,
            "steps": [{"name": evidence.EVIDENCE_STEP, "status": "completed", "conclusion": "success"}]}
        self.responses[f"{prefix}/actions/runs/123456"] = self.parent
        self.responses[f"{prefix}/actions/runs/123456/attempts/1/jobs?per_page=100"] = [{"total_count": 1, "jobs": [self.job]}]
        for record in self.records.values():
            self.responses[f"{prefix}/actions/runs/{record['run_id']}"] = fixture.run_payload(record, "failure")
            self.responses[f"{prefix}/actions/runs/{record['run_id']}/attempts/1/jobs?per_page=100"] = [{
                "total_count": 2, "jobs": [fixture.job_payload(record, conclusion="failure"), fixture.job_payload(record, summary=True)]}]

    def api(self, endpoint, **kwargs):
        if kwargs.get("payload") is not None:
            raise AssertionError("evidence preparation must never write to GitHub")
        self.calls.append(endpoint)
        if endpoint.endswith("/logs"):
            return b"Download failed\nAuthorization: secret\ncurl failed"
        return deepcopy(self.responses[endpoint])

    def contexts(self):
        with mock.patch.object(evidence, "read_source", return_value="name: Test package\n"):
            return evidence.contexts_from_audit(self.audit, api=self, repository=fixture.REPOSITORY,
                sha=fixture.SHA, run_id=123456, attempt=1, root=Path("."),
                topology=tuple(fixture.definition(batch) for batch in range(1, 23)))


class PersistentFailureTests(unittest.TestCase):
    def setUp(self):
        self.f = EvidenceFixture()

    def test_valid_live_confirmation_produces_exact_package_context(self):
        context, = self.f.contexts()
        self.assertEqual(context["package_slug"], "package-1")
        self.assertEqual(context["workflow_path"], ".github/workflows/test-package-1.yml")
        self.assertEqual(context["confirmation_run_id"], 20001)
        self.assertEqual(context["orchestration_id"], fixture.ORCHESTRATION)
        self.assertNotIn("Authorization", context["log_excerpt"])
        self.assertIn("credential-bearing", context["log_excerpt"])

    def test_nonpersistent_failure_does_not_authorize_model(self):
        del self.f.audit["failed_batches"]
        self.assertEqual(self.f.contexts(), [])
        self.assertEqual(self.f.calls, [])

    def test_audit_mutations_fail_closed(self):
        mutations = [
            lambda a: a.update(status="superseded"),
            lambda a: a.update(failed_batches=[True]),
            lambda a: a.update(failed_batches=[1, 1]),
            lambda a: a.update(failed_batches=[23]),
            lambda a: a["history"].append(deepcopy(a["history"][1])),
            lambda a: a["history"][1].update(retry=True),
            lambda a: a["history"][1].update(classification="success"),
            lambda a: a["history"][1].update(run_id=333),
            lambda a: a["dispatches"][0].update(run_attempt=True),
            lambda a: a["dispatches"][0].update(reason="unknown"),
            lambda a: a["dispatches"][0].update(expected_sha=fixture.OTHER_SHA),
            lambda a: a["dispatches"][0].update(run_id=10001),
            lambda a: a["dispatches"][0].update(dispatch_nonce=f"{1:064x}"),
            lambda a: a["original_manifest"].update(orchestration_id="orchestration-777-1"),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.f = EvidenceFixture()
                mutation(self.f.audit)
                with self.assertRaises((ValueError, TypeError)):
                    self.f.contexts()

    def test_api_run_identity_mutations_fail_closed(self):
        endpoint = f"repos/{fixture.REPOSITORY}/actions/runs/20001"
        for key, value in (("head_sha", fixture.OTHER_SHA), ("head_branch", "production"),
                ("id", 20002), ("run_attempt", 2), ("path", ".github/workflows/test-nginx.yml"),
                ("conclusion", "success"), ("status", "in_progress"),
                ("head_repository", {"full_name": "other/repo"})):
            with self.subTest(key=key):
                self.f = EvidenceFixture()
                self.f.responses[endpoint][key] = value
                with self.assertRaises(ValueError):
                    self.f.contexts()

    def test_extra_or_contradictory_confirmation_history_fails_closed(self):
        for entry in (
            {"batch": 1, "retry": 2, "run_id": 30001, "classification": "failed"},
            {"batch": 1, "retry": -1, "run_id": 30001, "classification": "failed"},
            {"batch": 1, "retry": "1", "run_id": 30001, "classification": "failed"},
            {"batch": 2, "retry": 1, "run_id": 30001, "classification": "failed"},
        ):
            with self.subTest(entry=entry):
                self.f = EvidenceFixture()
                self.f.audit["history"].append(entry)
                with self.assertRaises(ValueError):
                    self.f.contexts()
                self.assertEqual(self.f.calls, [])

    def test_both_package_failures_require_completed_unambiguous_failed_steps(self):
        for record_name in ("original", "replacement"):
            for mutation in (
                lambda job: job.update(steps=[]),
                lambda job: job["steps"][0].update(conclusion="success"),
                lambda job: job["steps"][0].update(status="in_progress"),
                lambda job: job["steps"][0].update(name=""),
                lambda job: job["steps"][0].update(number=True),
                lambda job: job["steps"].append(deepcopy(job["steps"][0])),
                lambda job: job["steps"][0].update(started_at=fixture.UPDATED),
            ):
                with self.subTest(run=record_name, mutation=mutation):
                    self.f = EvidenceFixture()
                    record = getattr(self.f, record_name)
                    endpoint = f"repos/{fixture.REPOSITORY}/actions/runs/{record['run_id']}/attempts/1/jobs?per_page=100"
                    mutation(self.f.responses[endpoint][0]["jobs"][0])
                    with self.assertRaises(ValueError):
                        self.f.contexts()
                    self.assertFalse(any(call.endswith("/logs") for call in self.f.calls))

    def test_failed_collector_and_incomplete_jobs_are_not_repairable(self):
        endpoint = f"repos/{fixture.REPOSITORY}/actions/runs/20001/attempts/1/jobs?per_page=100"
        for mutate in (lambda p: p[0]["jobs"][1].update(conclusion="failure"),
                lambda p: p[0].update(total_count=3), lambda p: p[0]["jobs"].pop()):
            self.f = EvidenceFixture()
            mutate(self.f.responses[endpoint])
            with self.assertRaises(ValueError):
                self.f.contexts()

    def test_main_advance_after_reading_evidence_stops_repair(self):
        self.f.responses[f"repos/{fixture.REPOSITORY}/git/ref/heads/main"] = fixture.branch_ref(fixture.OTHER_SHA)
        with self.assertRaises(ValueError):
            self.f.contexts()

    def test_only_the_same_registered_package_failing_both_runs_is_eligible(self):
        for original_outcomes, confirmation_outcomes, expected in (
            (("failure", "success"), ("success", "failure"), []),
            (("failure", "failure"), ("success", "failure"), ["second"]),
            (("failure", "success"), ("failure", "failure"), ["package-1"]),
        ):
            with self.subTest(original=original_outcomes, confirmation=confirmation_outcomes):
                f = EvidenceFixture()
                topology = [fixture.definition(batch) for batch in range(1, 23)]
                first = topology[0].packages[0]
                second = replace(first, job="test-second", workflow_path=".github/workflows/test-second.yml", package_slug="second")
                topology[0] = replace(topology[0], packages=(first, second))
                for record, outcomes in ((f.original, original_outcomes), (f.replacement, confirmation_outcomes)):
                    jobs = []
                    for index, (registration, conclusion) in enumerate(zip((first, second), outcomes)):
                        job = fixture.job_payload(record, conclusion=conclusion)
                        job["id"] += index * 2
                        job["name"] = evidence.expected_job_name(registration)
                        job["html_url"] = f"https://github.com/{fixture.REPOSITORY}/actions/runs/{record['run_id']}/job/{job['id']}"
                        jobs.append(job)
                    jobs.append(fixture.job_payload(record, summary=True))
                    endpoint = f"repos/{fixture.REPOSITORY}/actions/runs/{record['run_id']}/attempts/1/jobs?per_page=100"
                    f.responses[endpoint] = [{"total_count": len(jobs), "jobs": jobs}]
                with mock.patch.object(evidence, "read_source", return_value="name: Test package\n"):
                    contexts = evidence.contexts_from_audit(f.audit, api=f, repository=fixture.REPOSITORY,
                        sha=fixture.SHA, run_id=123456, attempt=1, root=Path("."), topology=tuple(topology))
                self.assertEqual([context["package_slug"] for context in contexts], expected)


class ParentAndArchiveTests(unittest.TestCase):
    def setUp(self):
        self.f = EvidenceFixture()

    def authenticate(self):
        return evidence.authenticate_parent(self.f, fixture.REPOSITORY, fixture.SHA, 123456, 1)

    def test_valid_parent_and_notification_only_attempt(self):
        self.assertEqual(self.authenticate()["id"], 99)
        self.f.parent["run_attempt"] = 2
        self.assertEqual(self.authenticate()["run_attempt"], 1)

    def test_invalid_parent_is_rejected(self):
        mutations = [lambda f: f.parent.update(head_sha=fixture.OTHER_SHA),
            lambda f: f.parent.update(run_attempt=True), lambda f: f.parent.update(event="pull_request"),
            lambda f: f.job.update(conclusion="success"), lambda f: f.job.update(conclusion="timed_out"),
            lambda f: f.job.update(run_attempt=True), lambda f: f.job.update(run_id=99),
            lambda f: f.job.update(status="in_progress"),
            lambda f: f.job["steps"][0].update(conclusion="failure"),
            lambda f: f.responses[f"repos/{fixture.REPOSITORY}"].update(private=True)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.f = EvidenceFixture()
                mutation(self.f)
                with self.assertRaises(ValueError):
                    self.authenticate()

    @staticmethod
    def archive(entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return output.getvalue()

    def test_unique_bounded_audit_is_read_without_extraction(self):
        raw = self.archive([("recovery-audit.json", json.dumps(self.f.audit))])
        self.assertEqual(evidence.read_audit_archive(raw), self.f.audit)

    def test_unsafe_duplicate_missing_and_ambiguous_archive_entries(self):
        for entries in [[], [("x", "{}")], [("../x", "{}"), ("recovery-audit.json", "{}")],
                [("recovery-audit.json", "{}"), (".orchestration/recovery-audit.json", "{}")],
                [("recovery-audit.json", '{"x":1,"x":2}')]]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                evidence.read_audit_archive(self.archive(entries))

    def test_digest_identity_size_and_creation_window_are_verified(self):
        raw = self.archive([("recovery-audit.json", json.dumps(self.f.audit))])
        endpoint = f"repos/{fixture.REPOSITORY}/actions/artifacts/55"
        metadata = {"id": 55, "name": "smoke-orchestration-evidence-123456-1", "expired": False,
            "workflow_run": {"id": 123456, "head_sha": fixture.SHA, "head_branch": "main"},
            "created_at": fixture.STEP_END, "size_in_bytes": len(raw),
            "digest": f"sha256:{hashlib.sha256(raw).hexdigest()}"}
        self.f.responses[endpoint] = metadata
        self.f.responses[endpoint + "/zip"] = raw
        def download():
            return evidence.download_audit(self.f, fixture.REPOSITORY, fixture.SHA, 123456, 1, 55, self.f.job)
        self.assertEqual(download(), self.f.audit)
        for key, value in (("id", True), ("name", "other"), ("expired", 0),
                ("digest", "sha256:" + "0" * 64), ("size_in_bytes", len(raw) + 1),
                ("created_at", fixture.UPDATED)):
            with self.subTest(key=key):
                self.f.responses[endpoint] = dict(metadata, **{key: value})
                with self.assertRaises(ValueError):
                    download()

    def test_regular_file_and_output_creation_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data.json"
            evidence.write_json(path, {"valid": True})
            self.assertEqual(evidence.read_json(path), {"valid": True})
            with self.assertRaises(FileExistsError):
                evidence.write_json(path, {})
            link = Path(temporary) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                evidence.read_json(link)

    def test_archive_directory_is_bounded_before_zipinfo_allocation(self):
        entries = [(f"registration-{number}.json", "{}") for number in range(202)]
        entries.append(("recovery-audit.json", "{}"))
        raw = self.archive(entries)
        with mock.patch.object(evidence.zipfile, "ZipFile") as reader:
            with self.assertRaises(ValueError):
                evidence.read_audit_archive(raw)
            reader.assert_not_called()

    def test_full_22_batch_audit_archive_shape_is_supported(self):
        entries = [(f"{kind}-{number}.json", "{}") for number in range(1, 23)
                   for kind in ("dispatch", "registration", "run", "nonce")]
        entries += [("recovery-audit.json", json.dumps(self.f.audit)), ("run-manifest.json", "{}")]
        self.assertEqual(evidence.read_audit_archive(self.archive(entries)), self.f.audit)


class SourceAndCLITests(unittest.TestCase):
    def test_redaction_precedes_excerpt_truncation(self):
        material = "SYNTHETIC-PRIVATE-MATERIAL"
        for raw in (
            "-----BEGIN PRIVATE KEY-----\n" + (material + "\n") * 1024 + "-----END PRIVATE KEY-----\n",
            "api_key=" + "x" * evidence.MAX_LOG_EXCERPT + material + "\n",
        ):
            with self.subTest(prefix=raw[:32]):
                excerpt = evidence.sanitize_log(raw.encode())
                self.assertNotIn(material, excerpt)
                self.assertIn("removed", excerpt)
                self.assertLessEqual(len(excerpt), evidence.MAX_LOG_EXCERPT)

    def test_sanitized_tail_retains_useful_diagnostics_without_credentials(self):
        raw = ("old diagnostic\n" * 1024
               + "Authorization: synthetic-credential\n"
               + "Download https://example.org/package?signature=synthetic-query\n"
               + "curl failed\n")
        excerpt = evidence.sanitize_log(raw.encode())
        self.assertNotIn("synthetic-credential", excerpt)
        self.assertNotIn("synthetic-query", excerpt)
        self.assertTrue(excerpt.endswith("curl failed"))
        self.assertLessEqual(len(excerpt), evidence.MAX_LOG_EXCERPT)

    def test_source_size_is_checked_before_loading_blob(self):
        source = b"name: test\n"
        with mock.patch.object(evidence.subprocess, "run", side_effect=[
            subprocess.CompletedProcess([], 0, str(len(source)).encode()),
            subprocess.CompletedProcess([], 0, source),
        ]) as run:
            self.assertEqual(evidence.read_source(Path("."), fixture.SHA, ".github/workflows/test-example.yml"), source.decode())
            self.assertEqual(run.call_args_list[0].args[0][3:5], ["cat-file", "-s"])
        for size in (b"0", b"131073", b"123456789", b"-1", b"blob"):
            with self.subTest(size=size), mock.patch.object(evidence.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], 0, size)) as run:
                with self.assertRaises(ValueError):
                    evidence.read_source(Path("."), fixture.SHA, ".github/workflows/test-example.yml")
                self.assertEqual(run.call_count, 1)

    def test_bad_source_paths_never_start_git(self):
        for path in (None, "../test-example.yml", ".github/workflows/main.yml",
                     ".github/workflows/test-all-packages-batch-1.yml"):
            with self.subTest(path=path), mock.patch.object(evidence.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    evidence.read_source(Path("."), fixture.SHA, path)
                run.assert_not_called()

    def test_cli_publishes_only_authenticated_context_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, environment = root / "contexts.json", root / "outputs"
            contexts = [{"package_slug": "nginx"}]
            args = ["--repository", fixture.REPOSITORY, "--base-sha", fixture.SHA,
                    "--run-id", "123456", "--attempt", "1", "--artifact-id", "55", "--output", str(output)]
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(environment)}), \
                 mock.patch.object(evidence, "validate_checkout_binding"), \
                 mock.patch.object(evidence, "GitHub"), \
                 mock.patch.object(evidence, "authenticate_parent") as parent, \
                 mock.patch.object(evidence, "download_audit") as archive, \
                 mock.patch.object(evidence, "contexts_from_audit", return_value=contexts):
                self.assertEqual(evidence.main(args), 0)
                self.assertEqual(parent.call_args.args[-2:], (123456, 1))
                self.assertEqual(archive.call_args.args[-4:-1], (123456, 1, 55))
            self.assertEqual(evidence.read_json(output), {"schema_version": 1, "contexts": contexts})
            self.assertEqual(environment.read_text(), 'eligible=true\nmatrix={"include":[{"slug":"nginx"}]}\n')

    def test_cli_rejects_untrusted_checkout_before_api_and_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "contexts.json"
            with mock.patch.object(evidence, "validate_checkout_binding", side_effect=ValueError("untrusted")), \
                 mock.patch.object(evidence, "GitHub") as api, mock.patch("sys.stderr", new_callable=io.StringIO) as errors:
                result = evidence.main(["--repository", fixture.REPOSITORY, "--base-sha", fixture.SHA,
                    "--run-id", "123456", "--attempt", "1", "--artifact-id", "55", "--output", str(output)])
            self.assertEqual(result, 1)
            api.assert_not_called()
            self.assertFalse(output.exists())
            self.assertNotIn("untrusted", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
