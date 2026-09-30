"""Process-local cache invalidation and real 22-batch recursive quota tests."""

from copy import copy, deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
import zipfile
import yaml

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

import smoke_repair_bundle as bundle
import smoke_repair_cycle_bridge as cycle
import smoke_repair_cycle_context as context_helper
import smoke_repair_evidence as evidence
import smoke_repair_fleet as fleet
from smoke_repair_session import VerificationSession, session_for
import test_smoke_repair_bridge as bridge_fixture
import test_smoke_repair_fleet as fleet_fixture
import test_smoke_repair_publisher as publisher_fixture
from test_smoke_repair_policy import SOURCE

PREFIX = f"repos/{fleet.REPOSITORY}"
ROOT = Path(__file__).resolve().parents[2]
EXPAND_CONTEXTS = context_helper.expand_contexts
CONTROLLER_RUNTIME = bundle._controller_runtime


def archive(document, name="feedback.json"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(name, json.dumps(document))
    return stream.getvalue()


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.run = PREFIX + "/actions/runs/501"
        self.ref = PREFIX + "/git/ref/heads/main"
        self.artifacts = self.run + "/artifacts?per_page=100"
        self.state = {
            self.run: {"id": 501, "run_attempt": 1, "status": "completed", "conclusion": "failure"},
            self.ref: {"ref": "refs/heads/main", "object": {"sha": "a" * 40}},
            self.artifacts: {"total_count": 1, "artifacts": [{"id": 601, "expired": False,
                "digest": "sha256:" + "a" * 64, "size_in_bytes": 5}]},
        }
        self.api = Mock()
        self.api.api.side_effect = lambda endpoint, **_: deepcopy(self.state[endpoint])
        self.session = VerificationSession(wall_clock=lambda: 100)
        self.builds = 0

    def build(self, api):
        self.builds += 1
        for endpoint in self.state:
            api.api(endpoint)
        return {"validated": [1]}

    def verify(self, build=None, **kwargs):
        return self.session.verify("test", {"sha": "a" * 40}, self.api, build or self.build, root=ROOT, **kwargs)

    def test_cache_hit_is_detached_and_every_boundary_refreshes_mutable_dependencies(self):
        self.verify()["validated"].append(2)
        self.api.api.reset_mock()
        self.assertEqual({"validated": [1]}, self.verify())
        self.assertEqual(1, self.builds)
        self.assertEqual(3, self.api.api.call_count)

    def test_rerun_ref_movement_deletion_and_digest_change_invalidate_cache(self):
        for change in (lambda: self.state[self.run].update(run_attempt=2),
                       lambda: self.state[self.ref]["object"].update(sha="b" * 40),
                       lambda: self.state[self.artifacts].update(total_count=0, artifacts=[]),
                       lambda: self.state[self.artifacts]["artifacts"][0].update(digest="sha256:" + "b" * 64),
                       lambda: self.state[self.artifacts]["artifacts"][0].update(expired=True)):
            with self.subTest(change=change):
                self.setUp()
                self.verify()
                change()
                with self.assertRaises(cycle.ContractError):
                    self.verify()
                self.assertFalse(self.session._entries)

    def test_attempt_specific_producer_requires_latest_even_on_first_verification(self):
        attempt = self.run + "/attempts/1"
        self.state[attempt] = deepcopy(self.state[self.run])
        self.verify(lambda api: api.api(attempt))
        self.state[self.run]["run_attempt"] = 2
        with self.assertRaises(cycle.ContractError):
            self.verify(lambda api: api.api(attempt))
        with self.assertRaises(cycle.ContractError):
            self.verify(lambda api: api.api(attempt))

    def test_nested_dependency_is_refreshed_once_and_expiry_is_transitive(self):
        def outer(api):
            for _ in range(4):
                self.session.verify("child", {}, api, self.build, root=ROOT, window=(0, 101))
            return {"ok": True}
        self.verify(outer)
        self.assertEqual(1, self.builds)
        self.api.api.reset_mock()
        self.verify(outer)
        self.assertEqual(3, self.api.api.call_count)
        with self.assertRaises(cycle.ContractError):
            self.verify(outer, now=102)

    def test_no_failed_result_recursive_entry_or_mock_session_is_reused(self):
        def fail(api):
            self.build(api)
            raise ValueError("failure")
        with self.assertRaises(ValueError):
            self.verify(fail)
        self.assertFalse(self.session._entries)
        with self.assertRaises(cycle.ContractError):
            self.verify(lambda api: self.verify())
        with self.assertRaises(cycle.ContractError):
            fleet.FleetValidation(session=Mock())
        self.assertIsNone(session_for(Mock()))

    def test_quota_sleep_restarts_checks_already_read_before_the_sleep(self):
        def read(endpoint, **options):
            result = deepcopy(self.state[endpoint])
            if endpoint == self.artifacts and self.api.api.call_count == 6:
                self.state[self.ref]["object"]["sha"] = "f" * 40
                self.session.after_wait()
            return result
        self.api.api.side_effect = read
        with self.assertRaises(cycle.ContractError):
            self.verify()
        self.assertFalse(self.session._entries)

    def test_cli_research_scope_uses_only_explicit_read_credential(self):
        import smoke_repair_upstream as upstream
        for module in (cycle, bundle, fleet):
            for token in (None, "public-read-token"):
                environment = {"GH_TOKEN": "write-capable-publisher-token"}
                if token:
                    environment["SMOKE_REPAIR_UPSTREAM_READ_TOKEN"] = token
                with self.subTest(module=module.__name__, token=token), \
                        patch.dict(bundle.os.environ, environment, clear=True), \
                        patch.object(upstream, "research_session") as scope, \
                        patch.object(module, "_main", return_value=0):
                    self.assertEqual(0, module.main([]))
                    scope.assert_called_once_with(metadata_token=token)
                    scope.return_value.__exit__.assert_called_once()


class QuotaAPI(fleet_fixture.FakeAPI):
    """Existing artifact fixtures, with actual shared 1,000/hour accounting."""
    def __init__(self, topology, origin, epoch):
        super().__init__(topology)
        self.origin, self.epoch, self.elapsed = origin, epoch, 0
        self.responses = {}
        self.branches = {}
        self.charged = 0
        self.hour = 0
        self.used = 0
        self.enforce_quota = False
        self.limit = 1000
        self.waits = []
        self.queue_until = 0
        self.after_read = lambda endpoint: None

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.elapsed += seconds

    def now(self):
        return self.epoch + self.elapsed

    def api(self, endpoint, *, payload=None, **kwargs):
        if endpoint == "rate_limit":
            hour = int(self.elapsed // 3600)
            if hour != self.hour:
                self.hour, self.used = hour, 0
            return {"resources": {"core": {"limit": self.limit,
                "remaining": self.limit - self.used, "reset": int(self.epoch + (hour + 1) * 3600)}}}
        self.charged += 1
        if self.enforce_quota:
            hour = int(self.elapsed // 3600)
            if hour != self.hour:
                self.hour, self.used = hour, 0
            self.used += 1
            if self.used > self.limit:
                raise AssertionError("actual hourly quota exceeded")
        self.calls.append((endpoint, deepcopy(payload)))
        if endpoint in self.responses:
            result = deepcopy(self.responses[endpoint])
        elif endpoint in self.origin.responses or endpoint.endswith("/logs"):
            result = self.origin.api(endpoint, **kwargs)
        elif "/git/ref/heads/" in endpoint:
            branch = endpoint.split("/git/ref/heads/")[1]
            result = {"ref": "refs/heads/" + branch,
                      "object": {"type": "commit", "sha": self.branches[branch]}}
        else:
            result = super()._api(endpoint, payload)
            if "/actions/workflows/" in endpoint and "/runs?" in endpoint:
                branch = parse_qs(urlsplit(endpoint).query)["branch"][0]
                rows = [r for r in result["workflow_runs"] if r["head_branch"] == branch]
                result = {"total_count": len(rows), "workflow_runs": rows}
            if ("/actions/runs/" in endpoint and isinstance(result, dict)
                    and result.get("head_branch") == self.descriptor["branch"]
                    and self.elapsed < self.queue_until):
                result = dict(result, status="in_progress", conclusion=None)
        self.after_read(endpoint)
        return deepcopy(result)

    def _new_run(self, batch, payload):
        stamp = datetime.fromtimestamp(self.now(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with patch.object(fleet_fixture, "CANDIDATE", self.descriptor["candidate_sha"]), \
                patch.object(fleet_fixture, "TIME", stamp):
            super()._new_run(batch, payload)
        run_id = max(self.runs)
        nonce = payload["inputs"]["dispatch_nonce"]
        self.runs[run_id]["display_title"] = fleet.orchestration.expected_run_name(
            batch.batch, "orchestration-123456-1", nonce)
        artifact = self.artifacts[run_id]
        with zipfile.ZipFile(io.BytesIO(self.archives[artifact["id"]])) as source:
            members = {name: source.read(name) for name in source.namelist()}
        sentinel = json.loads(members[fleet.batch_attestation.SENTINEL_NAME])
        sentinel["orchestration_id"] = "orchestration-123456-1"
        members[fleet.batch_attestation.SENTINEL_NAME] = (fleet.exact.canonical_json(sentinel) + "\n").encode()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as output:
            for name, raw in members.items():
                output.writestr(name, raw)
        raw = stream.getvalue()
        self.archives[artifact["id"]] = raw
        artifact.update(size_in_bytes=len(raw), digest="sha256:" + hashlib.sha256(raw).hexdigest())


class CycleBudgetTests(unittest.TestCase):
    def setUp(self):
        import builtins
        from test_smoke_repair_fleet import FleetTests
        self.fleet_case = FleetTests("test_persistent_failure_returns_complete_authentic_feedback")
        with patch.object(fleet_fixture, "enumerate", lambda items, start=0: builtins.enumerate(
                tuple(f"package-{i}" for i in range(1, 23)) if items == ("alpha", "bravo") else items,
                start), create=True):
            self.fleet_case.setUp()
        self.addCleanup(self.fleet_case.doCleanups)
        self.root, self.topology = self.fleet_case.root, self.fleet_case.topology
        self.original = bridge_fixture.EvidenceTests()
        self.original.setUp()
        self.context = self.original.context
        source = SOURCE.replace("test-widget:", "test:").replace("widget", "package-1")
        self.source = source
        self.context["source_text"] = source
        self.original.raw = bridge_fixture.archive({"schema_version": 1, "contexts": [self.context]})
        self.original.metadata.update(size_in_bytes=len(self.original.raw),
            digest="sha256:" + hashlib.sha256(self.original.raw).hexdigest())
        self.original.f.responses[PREFIX + "/actions/artifacts/700/zip"] = self.original.raw
        raw = archive(self.original.f.audit, "recovery-audit.json")
        audit_metadata = {**self.original.metadata, "id": 701,
            "name": "smoke-orchestration-evidence-123456-1", "size_in_bytes": len(raw),
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest()}
        self.original.inventory[0]["artifacts"][1] = audit_metadata
        self.original.f.responses[PREFIX + "/actions/artifacts/701"] = audit_metadata
        self.original.f.responses[PREFIX + "/actions/artifacts/701/zip"] = raw
        self.epoch = self.original.now + 120
        self.api = QuotaAPI(self.topology, self.original.f, self.epoch)
        self.api.failures = {1: [True] * 6}
        self.enterContext(patch.object(cycle, "authenticate_contexts", wraps=cycle.authenticate_contexts))
        self.auth = cycle.authenticate_contexts
        self.enterContext(patch.object(cycle, "compile_proposal", wraps=cycle.compile_proposal))
        self.compile = cycle.compile_proposal
        self.enterContext(patch.object(bridge_fixture.bridge, "select_context", return_value=self.context))
        self.enterContext(patch.object(evidence, "read_source", return_value=source))
        self.enterContext(patch.object(evidence, "discover_topology_at_commit",
            return_value=tuple(bridge_fixture.fixture.definition(i) for i in range(1, 23))))
        self.enterContext(patch.object(bundle, "_controller_runtime"))
        self.enterContext(patch.object(bundle.single, "_clean_base"))
        self.enterContext(patch.object(bundle.publisher, "Git"))
        self.enterContext(patch.object(bundle.publisher, "_assert_remote_base_unchanged"))
        self.enterContext(patch.object(bundle.publisher, "_remote_head_sha",
            side_effect=lambda git, branch: self.api.branches[branch]))
        self.enterContext(patch.object(bundle, "readmit", return_value={}))
        self.enterContext(patch.object(bundle, "_verify_branch", side_effect=lambda *args: args[-1]["attestation"]))
        self.enterContext(patch.dict(bundle.os.environ, {"SMOKE_REPAIR_APP_BOT_LOGIN": "repair[bot]",
            "DASHBOARD_DELIVERY_APP_BOT_LOGIN": "delivery[bot]"}))
        # Context expansion is owned/tested separately; these fleets introduce
        # no additional package, so the authenticated original stays unchanged.
        self.enterContext(patch("smoke_repair_cycle_context.expand_contexts", return_value=[self.context]))
        self.admissions, self.envelopes, self.receipts = {}, {}, {}
        for iteration in (1, 2, 3):
            request = {"schema_version": 2, "repository": fleet.REPOSITORY, "base_sha": fleet_fixture.BASE,
                "orchestrator_run_id": 123456, "orchestrator_attempt": 1, "context_artifact_id": 700,
                "cycle_id": "123456-1", "iteration": iteration,
                "previous_feedback_run_id": 500 + iteration - 1 if iteration > 1 else None,
                "previous_feedback_artifact_id": 900000 + iteration - 1 if iteration > 1 else None,
                "proposals": [{"package_slug": self.context["package_slug"],
                    "context_sha256": cycle.context_digest(self.context), "operations": [
                        {"kind": "prepend_parallelism", "step": 2, "variable": "MAKEFLAGS", "count": iteration}]}]}
            proposal = cycle.compile_proposal(self.context, request["proposals"][0]["operations"])
            admission = {"schema_version": 1, "request": request, "repairs": [
                {"context": self.context, "proposal": proposal}]}
            descriptor = {**fleet_fixture.DESCRIPTOR, "cycle_id": "123456-1", "iteration": iteration,
                "branch": cycle.candidate_branch("123456-1", iteration), "candidate_sha": str(iteration) * 40}
            self.api.branches[descriptor["branch"]] = descriptor["candidate_sha"]
            producer = {"run_id": 500 + iteration, "run_attempt": 1,
                "workflow_sha": fleet_fixture.BASE, "app_bot_login": "repair[bot]",
                "workflow_ref": f"{fleet.REPOSITORY}/{cycle.WORKFLOW}@refs/heads/main"}
            stamp = datetime.fromtimestamp(self.epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            audit = bundle._attestation({"request_digest": "a" * 64, "policy_version": "1", "packages": []},
                producer, "f" * 40, {"sha": "d" * 40, "tree_sha": "e" * 40, "verified_at": stamp})
            envelope = {"schema_version": 1, "admission": admission,
                "staged": {"candidate": descriptor, "attestation": audit}}
            controller = {"id": 500 + iteration, "run_attempt": 1, "event": "repository_dispatch",
                "head_branch": "main", "head_sha": fleet_fixture.BASE, "path": cycle.WORKFLOW,
                "status": "in_progress" if iteration == 3 else "completed",
                "conclusion": None if iteration == 3 else "failure", "created_at": stamp,
                "repository": {"full_name": fleet.REPOSITORY}, "head_repository": {"full_name": fleet.REPOSITORY}}
            endpoint = PREFIX + f"/actions/runs/{500 + iteration}"
            self.api.responses[endpoint] = controller
            self.api.responses[endpoint + "/attempts/1"] = deepcopy(controller)
            self.admissions[iteration], self.envelopes[iteration] = admission, envelope
            if iteration == 3:
                continue
            self.api.descriptor = descriptor
            receipt = self.worker().run(descriptor, repository_root=self.root, bundle_receipt=envelope,
                                       attest_candidate=lambda descriptor, *args, **kwargs: descriptor)
            self.receipts[iteration] = receipt
            raw = archive({"schema_version": 1, "bundle_receipt": envelope,
                "fleet_receipt": receipt, "contexts": [self.context]})
            artifact = {"id": 900000 + iteration,
                "name": f"smoke-repair-cycle-feedback-123456-1-{iteration}", "expired": False,
                "workflow_run": {"id": controller["id"], "head_sha": fleet_fixture.BASE, "head_branch": "main"},
                "created_at": stamp, "size_in_bytes": len(raw), "digest": "sha256:" + hashlib.sha256(raw).hexdigest()}
            self.api.responses[endpoint + "/artifacts?per_page=100"] = [{"total_count": 1, "artifacts": [artifact]}]
            self.api.responses[PREFIX + f"/actions/artifacts/{artifact['id']}/zip"] = raw
            job = {"id": 800000 + iteration, "run_id": controller["id"], "run_attempt": 1,
                "name": cycle.FEEDBACK_JOB, "head_sha": fleet_fixture.BASE, "status": "completed",
                "conclusion": "failure", "started_at": stamp, "completed_at": stamp,
                "steps": [{"name": name, "status": "completed", "conclusion": "success"} for name in cycle.FEEDBACK_STEPS]}
            self.api.responses[endpoint + "/attempts/1/jobs?per_page=100"] = [{"total_count": 1, "jobs": [job]}]
        self.api.descriptor = self.envelopes[3]["staged"]["candidate"]
        self.session = VerificationSession(wall_clock=self.api.now)
        self.api.enforce_quota = True
        self.api.charged = self.api.used = 0
        self.api.calls.clear()
        self.api.waits.clear()
        self.started = self.api.elapsed
        self.auth.reset_mock()
        self.compile.reset_mock()
        self.full_verifications = self.enterContext(patch.object(fleet.FleetValidation, "_verify",
            autospec=True, side_effect=fleet.FleetValidation._verify))

    def worker(self, session=None, *, api=None, **kwargs):
        api = self.api if api is None else api
        return fleet.FleetValidation(api=api, wall_clock=api.now,
            clock=lambda: api.elapsed, sleep=api.sleep, session=session, **kwargs)

    def native(self):
        return self.worker(self.session).run(self.api.descriptor, repository_root=self.root,
            bundle_receipt=self.envelopes[3], attest_candidate=bundle.attest_candidate)

    def local_origin(self, receipt):
        self.enterContext(patch.dict(bundle.os.environ, {
            "GITHUB_JOB": "native",
            "GITHUB_RUN_ID": "503", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": fleet.REPOSITORY, "GITHUB_SHA": fleet_fixture.BASE,
            "GITHUB_WORKFLOW_SHA": fleet_fixture.BASE, "GITHUB_EVENT_NAME": "repository_dispatch",
            "GITHUB_WORKFLOW_REF": f"{fleet.REPOSITORY}/{cycle.WORKFLOW}@refs/heads/main",
            "SMOKE_REPAIR_APP_SLUG": "repair", "GH_TOKEN": "test-publisher-token"}))
        self.enterContext(patch.object(bundle, "_controller_runtime", side_effect=CONTROLLER_RUNTIME))
        endpoint = PREFIX + "/actions/runs/503"
        self.api.responses[endpoint].update(status="in_progress", conclusion=None)
        self.api.responses[endpoint + "/attempts/1"].update(status="in_progress", conclusion=None)
        job = {"id": 800003, "run_id": 503, "run_attempt": 1, "name": cycle.FEEDBACK_JOB,
            "head_sha": fleet_fixture.BASE, "status": "in_progress", "conclusion": None,
            "started_at": receipt["started_at"], "steps": [{"name": cycle.NATIVE_STEP,
                "status": "completed", "conclusion": "success", "started_at": receipt["started_at"],
                "completed_at": receipt["completed_at"]}]}
        self.api.responses[endpoint + "/attempts/1/jobs?per_page=100"] = [{"total_count": 1, "jobs": [job]}]
        self.enterContext(patch.object(context_helper, "expand_contexts", side_effect=EXPAND_CONTEXTS))
        self.enterContext(patch.object(context_helper, "discover_topology_at_commit", return_value=self.topology))
        self.enterContext(patch.object(context_helper, "read_source", return_value=self.source))
        return job

    def feedback_cli(self, receipt):
        output = Path(self.enterContext(tempfile.TemporaryDirectory())) / "feedback"
        with patch.object(cycle, "read_json", side_effect=[self.envelopes[3], receipt]), \
                patch.object(cycle, "GitHub", return_value=self.api), \
                patch.object(cycle.time, "time", side_effect=self.api.now):
            self.assertEqual(0, cycle._main(["feedback", "--repository-root", str(self.root),
                "--bundle-receipt", "bundle.json", "--fleet-receipt", "receipt.json",
                "--output-dir", str(output)]))
        return json.loads((output / "feedback.json").read_text())

    def static_publication_preflight(self, receipt):
        # Exercise the workflow-owned pre-token code, not a replica in this test.
        workflow = yaml.safe_load((ROOT / "workflows/smoke-repair-cycle.yml").read_text())
        steps = workflow["jobs"]["publish"]["steps"]
        step = next(step for step in steps if step["name"] ==
                    "Readmit bundle and check receipt identity before delivery credentials")
        code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        staged = self.envelopes[3]["staged"]
        plan = {"request_digest": "a" * 64, "policy_version": "1", "packages": []}
        producer = staged["attestation"]["publisher"]
        anchor = {"sha": "d" * 40, "tree_sha": "e" * 40, "verified_at": receipt["started_at"]}
        staged["attestation"] = bundle._attestation(plan, producer, "f" * 40, anchor)
        with patch.object(bundle, "_load", side_effect=[self.envelopes[3], receipt]), \
                patch.object(bundle, "readmit", return_value=plan), \
                patch("smoke_repair_upstream.research_session"), \
                patch.dict(bundle.os.environ, {"RUNNER_TEMP": str(self.root.parent)}):
            exec(compile(code, str(ROOT / "workflows/smoke-repair-cycle.yml"), "exec"), {})

    def app_publication(self, receipt):
        # App quota is a different credential bucket, sharing evidence but not
        # the repository GITHUB_TOKEN counters. Preserve the latter untouched.
        app = copy(self.api)
        app.limit, app.used, app.charged = 5000, 0, 0
        app.calls, app.waits = [], []
        session = VerificationSession(wall_clock=app.now)
        worker = self.worker(session, api=app, timeout_seconds=fleet.VERIFY_SECONDS)
        reader = session.reader(worker)
        self.enterContext(patch.object(publisher_fixture, "REPOSITORY", fleet.REPOSITORY))
        github = publisher_fixture.FakeGitHub(Mock())
        create = github.create_pull_request

        def call(method, endpoint, payload=None):
            if "/pulls?" in endpoint:
                app.responses[endpoint] = deepcopy(github.prs)
            return app.api(endpoint, payload=payload)

        def create_pr(config, *, body, head_sha):
            result = create(config, body=body, head_sha=head_sha)
            endpoint = PREFIX + "/pulls"
            app.responses[endpoint] = result
            call("POST", endpoint, {"title": config.title, "body": body, "head": config.head_branch,
                                    "base": "main", "draft": True})
            return result

        github._api = call
        github.create_pull_request = create_pr
        github.list_open_pull_requests = lambda config: call("GET", PREFIX + "/pulls?state=open")
        envelope = self.envelopes[3]

        def current(request):
            return bundle._revalidate_admission(envelope["admission"], reader, self.root)

        def verify(descriptor, value):
            return worker.verify(descriptor, value, repository_root=self.root, bundle_receipt=envelope,
                                 attest_candidate=bundle.attest_candidate)

        result = bundle.open_draft(bundle.from_admission(envelope["admission"]), envelope["staged"], receipt,
            repository_root=self.root, validate_apply=Mock(), verify_current=current, verify_fleet=verify,
            github=github)
        self.assertEqual("created", result["status"])
        self.assertEqual(1, len(github.prs))
        self.assertIs(True, github.prs[0]["draft"])
        self.assertIsNone(github.prs[0]["auto_merge"])
        self.assertLess(app.charged, 5000)
        self.assertEqual([], app.waits)
        return app

    def test_sequential_native_feedback_preflight_and_draft_preserve_shared_quota(self):
        # Iteration three has one failed batch and a green confirmation. Other
        # jobs have already consumed part of this repository's shared bucket.
        self.api.failures[1] = [True] * 5
        self.api.used = 200
        receipt = self.native()
        self.assertEqual("success", receipt["status"])
        native_requests, native_used, completed = self.api.charged, self.api.used, self.api.elapsed
        self.local_origin(receipt)
        verified_before = self.full_verifications.call_count
        feedback = self.feedback_cli(receipt)
        self.assertEqual(receipt, feedback["fleet_receipt"])
        self.assertEqual([self.context], feedback["contexts"])
        self.assertEqual(verified_before, self.full_verifications.call_count)
        feedback_requests = self.api.charged - native_requests
        self.assertEqual(native_used + feedback_requests, self.api.used)
        self.static_publication_preflight(receipt)
        used_before_app = self.api.used
        app = self.app_publication(receipt)
        self.assertEqual(used_before_app, self.api.used)
        self.assertEqual(completed, self.api.elapsed)
        self.assertLess(self.api.used, 780)
        self.assertEqual(verified_before + 3, self.full_verifications.call_count)
        print(f"\nsequential iteration3: native {native_requests} requests/{native_used} current-hour; "
              f"feedback {feedback_requests}; preflight 0; GITHUB_TOKEN final {self.api.used}/1000; "
              f"App publication {app.charged}/5000; no post-native reset wait")

    def test_failed_native_feedback_packages_without_a_second_fleet_verification(self):
        receipt = self.native()
        self.local_origin(receipt)
        before, used, elapsed = self.full_verifications.call_count, self.api.used, self.api.elapsed
        feedback = self.feedback_cli(receipt)
        self.assertEqual("failure", feedback["fleet_receipt"]["status"])
        self.assertEqual(before, self.full_verifications.call_count)
        self.assertEqual(used + 8, self.api.used)
        self.assertEqual(elapsed, self.api.elapsed)
        print(f"\nfailed iteration3 feedback: preserves {used} used, finishes {self.api.used}/1000; no reset wait")

    def test_retry_admission_clis_share_quota_and_wait_with_one_bounded_deadline(self):
        original_init = fleet.FleetValidation.__init__
        sessions = []

        def initialize(worker, api=None, **options):
            options.setdefault("clock", lambda: self.api.elapsed)
            options.setdefault("sleep", self.api.sleep)
            options.setdefault("wall_clock", self.api.now)
            original_init(worker, self.api if api is None else api, **options)

        def new_session():
            session = VerificationSession(wall_clock=self.api.now)
            sessions.append(session)
            return session

        self.api.used = 770
        measurements = []
        # The second iteration-3 CLI is the stage job's independent pre-token
        # admission. It inherits the same hourly bucket, never the prior cache.
        for iteration in (2, 3, 3):
            request = self.admissions[iteration]["request"]
            branch = cycle.candidate_branch(request["cycle_id"], iteration)
            self.api.responses[PREFIX + f"/git/matching-refs/heads/{branch}"] = []
            self.api.responses[PREFIX + f"/pulls?state=all&head=ArmDeveloperEcosystem:{branch}&per_page=100"] = []
            output = Path(self.enterContext(tempfile.TemporaryDirectory())) / "admission"
            started, charged = self.api.elapsed, self.api.charged
            with patch.object(cycle, "read_json", return_value={}), \
                    patch.object(cycle, "validate_event", return_value=request), \
                    patch.object(cycle, "VerificationSession", side_effect=new_session), \
                    patch.object(cycle.time, "time", side_effect=self.api.now), \
                    patch.object(fleet.FleetValidation, "__init__", autospec=True, side_effect=initialize):
                self.assertEqual(0, cycle._main(["admit", "--event", "event.json",
                    "--repository-root", str(self.root), "--output-dir", str(output)]))
            self.assertEqual(self.admissions[iteration], json.loads((output / "admission.json").read_text()))
            self.assertLess(self.api.elapsed - started, cycle.ADMISSION_SECONDS)
            self.assertLess(self.api.used, 780)
            measurements.append((iteration, self.api.charged - charged, self.api.elapsed - started, self.api.used))
        self.assertEqual(3, len({id(session) for session in sessions}))
        self.assertGreater(sum(row[2] for row in measurements), 2 * fleet.VERIFY_SECONDS)
        print(f"\nshared-bucket admission (iteration, requests, wait seconds, hour used): {measurements}")

    def test_local_feedback_rejects_rerun_ref_move_foreign_producer_and_changed_receipt(self):
        receipt = self.native()
        job = self.local_origin(receipt)
        envelope = self.envelopes[3]
        run = self.api.responses[PREFIX + "/actions/runs/503"]
        changes = [
            (run, "run_attempt", 2),
            (job["steps"][0], "conclusion", "failure"),
            (job, "run_id", 502),
            (job, "status", "completed"),
            (envelope["staged"]["attestation"]["publisher"], "run_id", 502),
            (receipt, "completed_at", "2026-01-01T00:00:00Z"),
            (receipt["manifest"], "head_sha", "e" * 40),
            (receipt["summary"], "status", "success"),
            (receipt["attestation"], "manifest_sha256", "e" * 64),
            (receipt["attestation"]["batches"][0], "run_id", 100),
            (self.api.branches, self.api.descriptor["branch"], "e" * 40),
            (self.original.f.responses[PREFIX + "/git/ref/heads/main"]["object"], "sha", "e" * 40),
        ]
        for target, key, value in changes:
            old = target[key]
            try:
                with self.subTest(key=key), self.assertRaises((cycle.ContractError, bundle.PublishError)):
                    target[key] = value
                    cycle.package_feedback(envelope, receipt, self.root, self.api, now=self.api.now())
            finally:
                target[key] = old
        with patch.dict(bundle.os.environ, {"GITHUB_RUN_ATTEMPT": "2"}), self.assertRaises(bundle.PublishError):
            cycle.package_feedback(envelope, receipt, self.root, self.api, now=self.api.now())
        with patch.dict(bundle.os.environ, {"GITHUB_JOB": "publish"}), self.assertRaises(cycle.ContractError):
            cycle.package_feedback(envelope, receipt, self.root, self.api, now=self.api.now())

    def test_iteration_three_complete_native_fleet_stays_inside_real_hourly_quota(self):
        result = self.native()
        self.assertEqual("failure", result["status"])
        self.assertEqual(22, result["summary"]["batch_count"])
        self.assertEqual(1, self.auth.call_count)
        self.assertEqual(3, self.compile.call_count)
        self.assertEqual([1, 2], [call.args[1]["iteration"] for call in self.full_verifications.call_args_list][::-1])
        downloads = [endpoint for endpoint, _ in self.api.calls if endpoint.endswith("/zip")]
        self.assertEqual(len(downloads), len(set(downloads)))
        self.assertLessEqual(self.api.used, 1000)
        self.assertLess(self.api.elapsed, fleet.MAX_SECONDS)
        print(f"\niteration3 native: {self.api.charged} requests, {len(downloads)} archives, "
              f"{self.api.elapsed - self.started:g}s simulated wait, {self.api.used} current-hour requests")

    def test_long_queued_fleet_waits_for_reset_without_exceeding_quota(self):
        self.api.queue_until = self.started + 4200
        result = self.native()
        self.assertEqual("failure", result["status"])
        self.assertGreaterEqual(self.api.elapsed - self.started, 4200)
        self.assertLess(self.api.elapsed, fleet.MAX_SECONDS)
        self.assertTrue(any(wait != 300 for wait in self.api.waits))
        print(f"\nqueued iteration3: {self.api.charged} requests, {self.api.elapsed - self.started:g}s simulated wait")

    def test_sixteen_stage_guards_rebuild_each_ancestor_only_once(self):
        self.api.limit = 5000
        reader = self.session.reader(self.worker(self.session))
        for _ in range(16):
            cycle.revalidate_admission(self.admissions[3], reader, self.root, now=self.api.now())
        self.assertEqual(1, self.auth.call_count)
        self.assertEqual(3, self.compile.call_count)
        self.assertEqual(2, self.full_verifications.call_count)
        self.assertEqual([], self.api.waits)
        self.assertLess(self.api.charged, 5000)
        print(f"\n16 iteration3 stage guards: {self.api.charged} requests; "
              f"{self.auth.call_count} original audit; {self.full_verifications.call_count} ancestor fleets")

    def test_rerun_and_ref_move_after_cache_hit_are_not_authorized(self):
        self.native()
        admission = self.admissions[3]
        reader = self.session.reader(self.worker())
        cycle.revalidate_admission(admission, reader, self.root, now=self.api.now())
        self.api.responses[PREFIX + "/actions/runs/501"]["run_attempt"] = 2
        with self.assertRaises(cycle.ContractError):
            cycle.revalidate_admission(admission, reader, self.root, now=self.api.now())

    def test_reference_move_and_supersession_after_cache_hit_are_not_authorized(self):
        self.native()
        self.original.f.responses[PREFIX + "/git/ref/heads/main"]["object"]["sha"] = "e" * 40
        with self.assertRaises(cycle.ContractError):
            cycle.revalidate_admission(self.admissions[3], self.session.reader(self.worker()),
                                       self.root, now=self.api.now())

    def test_duplicate_cold_verification_cannot_fit_actual_post_native_shared_bucket(self):
        receipt = self.native()
        start, used, charged = self.api.elapsed, self.api.used, self.api.charged
        fresh = VerificationSession(wall_clock=self.api.now)
        with self.assertRaisesRegex(cycle.ContractError, "reserve"):
            self.worker(fresh, timeout_seconds=fleet.VERIFY_SECONDS).verify(
                self.api.descriptor, receipt, repository_root=self.root,
                bundle_receipt=self.envelopes[3], attest_candidate=bundle.attest_candidate)
        self.assertEqual(780, self.api.used)
        self.assertEqual(780 - used, self.api.charged - charged)
        self.assertEqual(start, self.api.elapsed)
        print(f"\nduplicate cold verify regression: starts {used}/1000 used, fails at reserve within 30min budget")

    def test_mutable_transitive_dependencies_are_not_skipped_by_cached_admission(self):
        self.native()
        first_run = self.receipts[1]["history"][0][0]["run_id"]
        branch = self.envelopes[1]["staged"]["candidate"]["branch"]
        changes = [
            (self.api.runs[first_run], "run_attempt", 2),
            (self.api.artifacts[first_run], "expired", True),
            (self.api.artifacts[first_run], "digest", "sha256:" + "e" * 64),
            (self.original.f.parent, "run_attempt", 2),
            (self.api.branches, branch, "e" * 40),
        ]
        entries = deepcopy(self.session._entries)
        self.api.limit = 5000
        for target, key, value in changes:
            with self.subTest(key=key):
                old = target[key]
                target[key] = value
                try:
                    with self.assertRaises(cycle.ContractError):
                        cycle.revalidate_admission(self.admissions[3], self.session.reader(self.worker(self.session)),
                                                   self.root, now=self.api.now())
                finally:
                    target[key] = old
                    self.session._entries = deepcopy(entries)
        inventory = self.original.f.responses[self.original.supersession]
        inventory["workflow_runs"].append(dict(self.original.f.parent, id=123457, run_number=101))
        inventory["total_count"] = 2
        with self.assertRaises(cycle.ContractError):
            cycle.revalidate_admission(self.admissions[3], self.session.reader(self.worker(self.session)),
                                       self.root, now=self.api.now())

    def test_current_candidate_producer_rerun_invalidates_attestation_cache(self):
        self.native()
        self.api.responses[PREFIX + "/actions/runs/503"]["run_attempt"] = 2
        with self.assertRaises(cycle.ContractError):
            bundle.attest_candidate(self.api.descriptor, self.envelopes[3],
                api=self.session.reader(self.worker(self.session)), repository_root=self.root)

    def test_wait_beyond_verification_deadline_cannot_report_success(self):
        receipt = self.native()
        self.api.used = 780
        with self.assertRaisesRegex(cycle.ContractError, "reserve"):
            self.worker(VerificationSession(wall_clock=self.api.now), timeout_seconds=30).verify(
                self.api.descriptor, receipt, repository_root=self.root,
                bundle_receipt=self.envelopes[3], attest_candidate=bundle.attest_candidate)


if __name__ == "__main__":
    unittest.main()
