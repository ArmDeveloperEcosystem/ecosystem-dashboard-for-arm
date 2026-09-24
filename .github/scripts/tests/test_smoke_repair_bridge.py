"""Callback identity, confidentiality, compilation, and exact-evidence tests."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_repair_bridge as bridge
from test_smoke_repair_evidence import EvidenceFixture
from test_smoke_repair_policy import SOURCE
from test_smoke_repair_pipeline import context
import test_smoke_recovery as fixture


def payload():
    return {"schema_version": 1, "repository": bridge.REPOSITORY, "base_sha": "a" * 40,
            "orchestrator_run_id": 123456, "orchestrator_attempt": 1,
            "context_artifact_id": 700, "package_slug": "widget", "context_sha256": "b" * 64,
            "operations": [{"kind": "prepend_apt", "step": 2, "packages": ["libfuse3-dev"]}]}


def event():
    return {"action": bridge.EVENT,
            "repository": {"full_name": bridge.REPOSITORY, "private": False, "default_branch": "main", "id": 123},
            "sender": {"login": "repair-bridge[bot]", "id": 456, "type": "Bot"},
            "client_payload": payload()}


def environment():
    return {"GITHUB_EVENT_NAME": "repository_dispatch", "GITHUB_REPOSITORY": bridge.REPOSITORY,
            "GITHUB_REF": "refs/heads/main", "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_SHA": "a" * 40, "GITHUB_WORKFLOW_SHA": "a" * 40,
            "GITHUB_WORKFLOW_REF": f"{bridge.REPOSITORY}/{bridge.WORKFLOW}@refs/heads/main",
            "SMOKE_REPAIR_ENABLED": "true", "SMOKE_REPAIR_BRIDGE_BOT_LOGIN": "repair-bridge[bot]",
            "SMOKE_REPAIR_BRIDGE_BOT_ID": "456", "GITHUB_ACTOR": "repair-bridge[bot]",
            "GITHUB_ACTOR_ID": "456", "GITHUB_REPOSITORY_ID": "123"}


def archive(document):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        zipped.writestr("contexts.json", json.dumps(document))
    return stream.getvalue()


class EventTests(unittest.TestCase):
    def test_exact_enabled_app_main_callback(self):
        self.assertEqual(payload(), bridge.validate_event(event(), environment()))

    def test_each_runtime_and_app_binding_is_required(self):
        for key in environment():
            with self.subTest(key=key):
                env = environment()
                del env[key]
                with self.assertRaises(ValueError):
                    bridge.validate_event(event(), env)

    def test_event_and_payload_mutations_fail_closed(self):
        changes = [lambda e: e.update(action="other"),
            lambda e: e["sender"].update(id=True), lambda e: e["sender"].update(id=457),
            lambda e: e["sender"].update(login="another[bot]"), lambda e: e["sender"].update(type="User"),
            lambda e: e["repository"].update(full_name="untrusted/repository"),
            lambda e: e["repository"].update(id=124), lambda e: e["repository"].update(private=True),
            lambda e: e["repository"].update(default_branch="production"),
            lambda e: e["client_payload"].update(schema_version=True),
            lambda e: e["client_payload"].update(base_sha="c" * 40),
            lambda e: e["client_payload"].update(orchestrator_run_id=True),
            lambda e: e["client_payload"].update(orchestrator_attempt=0),
            lambda e: e["client_payload"].update(context_artifact_id=-1),
            lambda e: e["client_payload"].update(package_slug="../../foo"),
            lambda e: e["client_payload"].update(context_sha256="not-a-digest"),
            lambda e: e["client_payload"].update(diagnosis="private free text"),
            lambda e: e["client_payload"].update(operations=[])]
        for change in changes:
            with self.subTest(change=change):
                candidate = event()
                change(candidate)
                with self.assertRaises(ValueError):
                    bridge.validate_event(candidate, environment())

    def test_unconfigured_receiver_has_no_side_effects_or_sensitive_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_path = root / "event.json"
            document = event()
            document["client_payload"]["secret"] = "never-log-private-canary"
            event_path.write_text(json.dumps(document))
            out, errors = io.StringIO(), io.StringIO()
            with mock.patch.dict(os.environ, environment(), clear=True), \
                    mock.patch.object(bridge, "authenticate_context") as auth, \
                    redirect_stdout(out), redirect_stderr(errors):
                code = bridge.main(["--event", str(event_path), "--output-directory", directory])
            self.assertEqual(code, 1)
            auth.assert_not_called()
            self.assertNotIn("never-log", out.getvalue() + errors.getvalue())
            self.assertEqual(list(root.iterdir()), [event_path])


class CompilationTests(unittest.TestCase):
    def compile(self, operations, source=SOURCE):
        return bridge.compile_proposal(context(source), operations)

    def test_apt_prerequisite_preserves_entire_existing_script(self):
        proposal = self.compile(payload()["operations"])
        edit, = proposal["edits"]
        self.assertIn("sudo apt-get install -y libfuse3-dev\n          set -euo pipefail", edit["new"])
        self.assertEqual(edit["old"], edit["new"].replace("          sudo apt-get install -y libfuse3-dev\n", "", 1))
        self.assertEqual(proposal["unresolved_reason"], "")

    def test_verified_upstream_operation_passes_independent_structural_admission(self):
        import smoke_repair_upstream as research
        import test_smoke_repair_upstream as upstream
        import smoke_repair_policy as policy
        source = SOURCE.replace("https://example.org/widget-1.2.3.tar.gz", upstream.OLD_URL)
        trusted = context(source)
        client = upstream.FakeClient()
        with mock.patch.object(research, "GitHubReleases", return_value=client):
            choice = research.research_downloads(trusted)["candidates"][0]
            operation = {"kind": "github_release_download", **{key: choice[key] for key in ("step", "line", "research_id")}}
            proposal = bridge.compile_proposal(trusted, [operation])
            admitted = policy.validate_proposal(trusted, proposal)
        self.assertIn(upstream.NEW_URL, admitted["candidate_source"])
        self.assertIn(upstream.SHA, admitted["candidate_source"])
        self.assertEqual(admitted["contract"], policy.derive_contract(source))
        tampered = deepcopy(proposal)
        tampered["edits"][0]["new"] += "          true # suppress failure\n"
        with mock.patch.object(research, "GitHubReleases", return_value=client), self.assertRaises(ValueError):
            policy.validate_proposal(trusted, tampered)
        with self.assertRaises(ValueError):
            bridge.compile_proposal(trusted, [operation, {"kind": "prepend_apt", "step": 2, "packages": ["libfuse3-dev"]}])

    def test_download_selection_cannot_supply_url_or_bypass_upstream_reverification(self):
        op = {"kind": "github_release_download", "step": 2, "line": 2, "research_id": "a" * 64}
        for change in ({"url": "https://private.invalid/"}, {"research_id": "not-a-hash"}, {"line": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                bridge.validate_operations([{**op, **change}])
        with mock.patch("smoke_repair_upstream.resolve_download_operation", side_effect=ValueError("not verified")), \
                self.assertRaises(ValueError):
            bridge.compile_proposal(context(), [op])

    def test_pip_parallelism_and_retry_pass_existing_independent_policy(self):
        operations = [
            {"kind": "prepend_pip", "step": 8, "packages": ["wheel"]},
            {"kind": "prepend_parallelism", "step": 8, "variable": "MAKEFLAGS", "count": 2},
            {"kind": "curl_retry", "step": 2, "line": 2, "retries": 2, "delay": 2, "seconds": 60},
        ]
        result = self.compile(operations)
        self.assertEqual(len(result["edits"]), 2)
        self.assertIn('--retry 2 --retry-delay 2 --retry-max-time 60', result["edits"][0]["new"])

    def test_model_cannot_supply_shell_paths_urls_comments_versions_or_extra_text(self):
        candidates = [
            [{"kind": "prepend_apt", "step": 2, "packages": ["curl; echo private"]}],
            [{"kind": "prepend_pip", "step": 2, "packages": ["wheel==private"]}],
            [{"kind": "prepend_apt", "step": 2, "packages": ["https://example.org/x"]}],
            [{"kind": "prepend_apt", "step": 2, "packages": ["cmake", "cmake"]}],
            [{"kind": "prepend_parallelism", "step": 8, "variable": "GITHUB_OUTPUT", "count": 1}],
            [{"kind": "prepend_parallelism", "step": 8, "variable": "MAKEFLAGS", "count": True}],
            [{"kind": "prepend_parallelism", "step": 8, "variable": "MAKEFLAGS", "count": 5}],
            [{"kind": "curl_retry", "step": 2, "line": 2, "retries": 6, "delay": 2, "seconds": 60}],
            [{"kind": "curl_retry", "step": 2, "line": 2, "retries": 1, "delay": 11, "seconds": 60}],
            [{"kind": "curl_retry", "step": 2, "line": 2, "retries": 1, "delay": 2, "seconds": True}],
            [{"kind": "shell", "step": 2, "command": "echo pass"}],
            [{**payload()["operations"][0], "diagnosis": "internal text"}],
            [{**payload()["operations"][0], "step": True}],
            [{**payload()["operations"][0], "step": 256}],
            payload()["operations"] * 13,
        ]
        for ops in candidates:
            with self.subTest(ops=ops), self.assertRaises(ValueError):
                self.compile(ops)

    def test_frozen_gates_and_non_script_steps_are_not_repairable(self):
        for step in (0, 1, 9, 10, 99):
            with self.subTest(step=step), self.assertRaises(ValueError):
                self.compile([{**payload()["operations"][0], "step": step}])

    def test_retry_cannot_rewrite_probe_or_apply_twice(self):
        operation = {"kind": "curl_retry", "step": 2, "line": 2, "retries": 2, "delay": 2, "seconds": 60}
        for ops in ([operation, operation], [{**operation, "line": 0}], [{**operation, "line": 999}]):
            with self.subTest(ops=ops), self.assertRaises(ValueError):
                self.compile(ops)

    def test_ambiguous_block_scalar_requires_manual_repair(self):
        for source in (SOURCE.replace("run: |", "run: >", 1), SOURCE.replace("\n", "\r\n"),
                SOURCE.replace("id: install\n        run: |", "id: install\n        run: | # special")):
            # A folded metadata script alone is irrelevant; target that metadata step as well.
            target = 1 if "run: >" in source else 2
            with self.subTest(source=source[:50]), self.assertRaises(ValueError):
                self.compile([{**payload()["operations"][0], "step": target}], source)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = EvidenceFixture()
        self.context = self.f.contexts()[0]
        self.p = payload()
        self.p.update(base_sha=fixture.SHA, package_slug=self.context["package_slug"], context_sha256=bridge.context_digest(self.context))
        self.f.parent.update(status="completed", conclusion="failure", created_at=fixture.STARTED, run_number=100)
        self.supersession = f"repos/{bridge.REPOSITORY}/actions/workflows/test-all-packages-orchestrator.yml/runs?branch=main&head_sha={fixture.SHA}&per_page=100&page=1"
        self.f.responses[self.supersession] = {"total_count": 1, "workflow_runs": [self.f.parent]}
        self.prepare = dict(self.f.job, id=100, name=next(name for name in bridge.PREPARE_JOBS if "/" in name), conclusion="success")
        self.f.responses[f"repos/{bridge.REPOSITORY}/actions/runs/123456/attempts/1/jobs?per_page=100"] = [{"total_count": 2, "jobs": [self.f.job, self.prepare]}]
        self.raw = archive({"schema_version": 1, "contexts": [self.context]})
        self.metadata = {"id": 700, "name": "smoke-repair-context-123456-1", "expired": False,
            "workflow_run": {"id": 123456, "head_sha": fixture.SHA, "head_branch": "main"},
            "size_in_bytes": len(self.raw), "digest": "sha256:" + hashlib.sha256(self.raw).hexdigest(),
            "created_at": fixture.COMPLETED}
        self.inventory = [{"total_count": 2, "artifacts": [self.metadata, {"id": 701, "name": "smoke-orchestration-evidence-123456-1"}]}]
        self.f.responses[f"repos/{bridge.REPOSITORY}/actions/runs/123456/artifacts?per_page=100"] = self.inventory
        self.f.responses[f"repos/{bridge.REPOSITORY}/actions/artifacts/700/zip"] = self.raw
        branch = "automation/smoke-repair/123456-1-package-1"
        self.refs = f"repos/{bridge.REPOSITORY}/git/matching-refs/heads/{branch}"
        self.pulls = f"repos/{bridge.REPOSITORY}/pulls?state=all&head=ArmDeveloperEcosystem:{branch}&per_page=100"
        self.f.responses[self.refs] = []
        self.f.responses[self.pulls] = []
        self.now = bridge.timestamp(fixture.COMPLETED).timestamp() + 1

    def authenticate(self):
        with mock.patch.object(bridge, "select_context", return_value=self.context), \
                mock.patch.object(bridge, "download_audit", return_value=self.f.audit), \
                mock.patch.object(bridge, "contexts_from_audit", return_value=[self.context]):
            return bridge.authenticate_context(self.p, self.f, Path("."), now=self.now)

    def test_exact_producer_artifact_digest_and_live_failure_admitted(self):
        self.assertEqual(self.context, self.authenticate())
        self.assertIn(self.refs, self.f.calls)

    def test_stale_wrong_or_incomplete_evidence_rejected(self):
        changes = [lambda: self.f.parent.update(status="in_progress"),
            lambda: self.f.parent.update(conclusion="success"), lambda: self.f.parent.update(run_attempt=2),
            lambda: self.prepare.update(conclusion="failure"), lambda: self.prepare.update(head_sha="f" * 40),
            lambda: self.metadata.update(expired=True), lambda: self.metadata.update(digest="sha256:" + "f" * 64),
            lambda: self.metadata.update(size_in_bytes=1), lambda: self.metadata["workflow_run"].update(id=456),
            lambda: self.metadata.update(created_at="2099-01-01T00:00:00Z"),
            lambda: self.inventory[0].update(total_count=3),
            lambda: self.p.update(context_sha256="f" * 64), lambda: self.p.update(context_artifact_id=701),
            lambda: self.f.responses.update({self.refs: [{"ref": "refs/heads/automation/smoke-repair/123456-1-package-1"}]}),
            lambda: self.f.responses.update({self.pulls: [{"state": "closed"}]}),
            lambda: setattr(self, "now", self.now + bridge.MAX_AGE)]
        for change in changes:
            with self.subTest(change=change):
                self.setUp()
                change()
                with self.assertRaises(ValueError):
                    self.authenticate()

    def test_other_package_prefix_does_not_count_as_replay(self):
        self.f.responses[self.refs] = [{"ref": "refs/heads/automation/smoke-repair/123456-1-package-1-extra"}]
        self.assertEqual(self.context, self.authenticate())

    def test_newer_run_at_same_sha_invalidates_failed_run_for_every_outcome(self):
        for state in ("success", "failure", "cancelled", None):
            with self.subTest(state=state):
                newer = dict(self.f.parent, id=123457, run_number=101, conclusion=state,
                             status="in_progress" if state is None else "completed")
                self.f.responses[self.supersession] = {"total_count": 2, "workflow_runs": [newer, self.f.parent]}
                with self.assertRaises(ValueError):
                    self.authenticate()

    def test_missing_duplicate_and_truncated_supersession_history_are_rejected(self):
        for rows in ({"total_count": 2, "workflow_runs": [self.f.parent]},
                     {"total_count": 2, "workflow_runs": [self.f.parent, self.f.parent]},
                     {"total_count": 0, "workflow_runs": []},
                     {"total_count": True, "workflow_runs": [self.f.parent]},
                     {"total_count": 1, "workflow_runs": [dict(self.f.parent, run_number=True)]}):
            self.f.responses[self.supersession] = rows
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.authenticate()

    def test_same_run_advancing_during_inventory_is_rejected(self):
        for change in ({"run_attempt": 2, "status": "in_progress", "conclusion": None},
                       {"status": "queued", "conclusion": None},
                       {"conclusion": "success"}, {"run_attempt": True}, {"run_number": 99}):
            with self.subTest(change=change):
                self.f.responses[self.supersession] = {
                    "total_count": 1, "workflow_runs": [{**self.f.parent, **change}]}
                with self.assertRaises(ValueError):
                    bridge.assert_current_failure(self.f.api, self.context, now=self.now)

    def test_same_run_advancing_after_inventory_is_rejected(self):
        endpoint = f"repos/{bridge.REPOSITORY}/actions/runs/123456"
        for change in ({"run_attempt": 2, "status": "in_progress", "conclusion": None},
                       {"status": "queued", "conclusion": None}, {"conclusion": "success"}):
            reads = 0

            def read(path):
                nonlocal reads
                if path == endpoint:
                    reads += 1
                    if reads == 2:
                        return {**self.f.parent, **change}
                return self.f.api(path)

            with self.subTest(change=change), self.assertRaises(ValueError):
                bridge.assert_current_failure(read, self.context, now=self.now)
            self.assertEqual(reads, 2)

    def test_publisher_rechecks_supersession_before_privileged_guard_completes(self):
        from test_smoke_repair_publisher import module as publisher
        config = publisher.RepairConfig(bridge.REPOSITORY, fixture.SHA, "123456-1-package-1", "repair[bot]")
        runtime = {"workflow_ref": f"{bridge.REPOSITORY}/{bridge.WORKFLOW}@refs/heads/main"}
        github = mock.Mock()
        github._api.side_effect = lambda method, endpoint: self.f.api(endpoint)
        with mock.patch.object(bridge.time, "time", return_value=self.now), \
                mock.patch.object(publisher, "_clean_base"), \
                mock.patch.object(publisher, "_runtime_guard"), \
                mock.patch.object(publisher.publisher, "_assert_remote_base_unchanged"):
            publisher._guard(Path("."), mock.Mock(), github, config, runtime)
            self.f.responses[self.supersession] = {"total_count": 2, "workflow_runs": [
                dict(self.f.parent, id=123457, run_number=101, conclusion="success"), self.f.parent]}
            with self.assertRaises(ValueError):
                publisher._guard(Path("."), mock.Mock(), github, config, runtime)
        self.assertTrue(all(call.args[0] == "GET" for call in github._api.call_args_list))

    def test_rebuilt_failure_identity_must_match_stored_context(self):
        with mock.patch.object(bridge, "select_context", return_value=self.context), \
                mock.patch.object(bridge, "download_audit", return_value=self.f.audit), \
                mock.patch.object(bridge, "contexts_from_audit", return_value=[dict(self.context, confirmation_job_id=999)]):
            with self.assertRaises(ValueError):
                bridge.authenticate_context(self.p, self.f, Path("."), now=self.now)

    def test_archive_rejects_extra_files_traversal_and_oversize(self):
        for filename in ("../contexts.json", "/contexts.json", "contexts.json/", "other.json"):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as zipped:
                zipped.writestr(filename, "{}")
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                bridge.context_archive(stream.getvalue())
        with self.assertRaises(ValueError):
            bridge.context_archive(b"x" * (bridge.MAX_ARCHIVE + 1))


if __name__ == "__main__":
    unittest.main()
