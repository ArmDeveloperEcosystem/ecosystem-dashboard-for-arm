from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import smoke_repair_fleet as fleet

REPOSITORY = fleet.REPOSITORY
BASE = "a" * 40
CANDIDATE = "b" * 40
TIME = "2026-09-24T12:00:00Z"
EPOCH = datetime.fromisoformat(TIME.replace("Z", "+00:00")).timestamp()
DESCRIPTOR = {"schema_version": 1, "repository": REPOSITORY, "base_sha": BASE,
    "candidate_sha": CANDIDATE, "cycle_id": "9000-1", "iteration": 1,
    "branch": "automation/smoke-repair-cycle/9000-1/iteration-1"}


def package_source(slug):
    text = f"name: Test {slug}\npermissions:\n  contents: read\njobs:\n  test:\n    runs-on: ubuntu-24.04-arm\n    steps:\n"
    for number in range(1, 7):
        text += f"      - name: Test {number} - bounded check\n        id: test{number}\n        run: true\n"
    return text + "      - name: Enforce failure status\n        if: always()\n        run: exit 0\n"


class FakeAPI:
    def __init__(self, topology):
        self.topology = topology
        self.runs, self.jobs, self.artifacts, self.archives = {}, {}, {}, {}
        self.calls = []
        self.failures = {}
        self.mutate = lambda endpoint, value: value
        self.main_sha, self.candidate_sha = BASE, CANDIDATE
        self.descriptor = deepcopy(DESCRIPTOR)
        self.ambiguous_post = False
        self.remaining = 5000
        self.pending = False

    def _new_run(self, batch, payload):
        run_id = 1000 + len(self.runs)
        prior = len([r for r in self.runs.values() if r["workflow_id"] == batch.batch])
        states = self.failures.get(batch.batch, [])
        failed = prior < len(states) and states[prior]
        nonce = payload["inputs"]["dispatch_nonce"]
        run = {"id": run_id, "run_attempt": 1, "workflow_id": batch.batch,
            "name": batch.workflow_name, "path": batch.workflow_path,
            "display_title": fleet.orchestration.expected_run_name(batch.batch, "orchestration-9000-1", nonce),
            "event": "workflow_dispatch", "head_branch": self.descriptor["branch"], "head_sha": CANDIDATE,
            "status": "completed", "conclusion": "failure" if failed else "success",
            "created_at": TIME, "updated_at": TIME, "run_started_at": TIME,
            "repository": {"full_name": REPOSITORY}, "head_repository": {"full_name": REPOSITORY},
            "head_commit": {"id": CANDIDATE}, "url": f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{run_id}",
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"}
        self.runs[run_id] = run
        package = batch.packages[0]
        job_id = run_id * 10
        job = {"id": job_id, "name": fleet.exact.expected_job_name(package), "run_id": run_id,
            "run_attempt": 1, "status": "completed", "conclusion": run["conclusion"],
            "head_sha": CANDIDATE, "head_branch": self.descriptor["branch"],
            "workflow_name": batch.workflow_name, "started_at": TIME, "completed_at": TIME,
            "labels": ["ubuntu-24.04-arm"], "runner_id": 99, "runner_name": "Hosted Agent",
            "runner_group_id": 0, "runner_group_name": "GitHub Actions", "run_url": run["url"],
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{job_id}",
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/job/{job_id}", "steps": []}
        for number in range(1, 9):
            name = "Set up job" if number == 1 else (
                "Enforce failure status" if number == 8 else f"Test {number - 1} - bounded check")
            conclusion = "failure" if failed and number in {7, 8} else "success"
            job["steps"].append({"name": name, "number": number, "status": "completed",
                "conclusion": conclusion, "started_at": TIME, "completed_at": TIME})
        self.jobs[job_id] = job
        summary = deepcopy(job)
        summary.update({"id": job_id + 1, "name": "summary", "conclusion": "success",
            "url": f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{job_id + 1}",
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/job/{job_id + 1}",
            "steps": [{"number": i + 2, "name": name, "status": "completed", "conclusion": "success",
                       "started_at": TIME, "completed_at": TIME}
                      for i, name in enumerate(("Collect", "Attest", "Upload"))]})
        self.jobs[job_id + 1] = summary
        statuses = ["passed"] * 5 + (["failed"] if failed else ["passed"])
        details = [{"name": f"Test {n} - bounded check", "status": status, "duration_seconds": 0,
                    "url": job["html_url"] + f"#step:{n + 1}:1"}
                   for n, status in enumerate(statuses, 1)]
        decision = "next_install_failed" if failed else "next_install_validated"
        details[-1].update(decision=decision, regression_result="Actual next install validation completed with recorded evidence.")
        result = {"schema_version": "2.0", "package": {"name": package.package_slug, "version": "1.2.3"},
            "run": {"id": str(run_id), "attempt": "1", "url": job["html_url"], "timestamp": TIME,
                    "status": run["conclusion"], "runner": {"os": "ubuntu-24.04", "arch": "arm64"}, "job_name": job["name"]},
            "tests": {"passed": statuses.count("passed"), "failed": statuses.count("failed"), "skipped": 0,
                      "duration_seconds": 0, "details": details},
            "metadata": {"contract_version": "2.0", "package_slug": package.package_slug,
                "dashboard_link": f"/linux/opensource_packages/{package.package_slug}",
                "badge_status": "failing" if failed else "passing", "core_failed": 0,
                "batch_title": f"Batch {batch.batch}", "job_url_resolution_status": "central_exact",
                "regression_status": statuses[-1], "regression_decision": decision,
                "regression_applicability": "applicable", "regression_reason": decision if failed else "validated",
                "regression_note": "Actual bounded native regression validation result."}}
        result_raw = (fleet.exact.canonical_json(result) + "\n").encode()
        result_path = f"{package.package_slug}-test-results/{package.package_slug}.json"
        sentinel = {"schema": fleet.batch_attestation.SCHEMA, "version": 1,
            "repository": REPOSITORY, "batch": batch.batch, "workflow": Path(batch.workflow_path).name,
            "artifact": batch.artifact_name, "orchestration_id": "orchestration-9000-1", "dispatch_nonce": nonce,
            "expected_sha": CANDIDATE, "branch": self.descriptor["branch"], "run_id": run_id, "run_attempt": 1,
            "collector": {"status": "success", "result_count": 1},
            "packages": [{"job": package.job, "workflow": Path(package.workflow_path).name,
                "package_slug": package.package_slug, "result_path": result_path,
                "sha256": hashlib.sha256(result_raw).hexdigest()}]}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(fleet.batch_attestation.SENTINEL_NAME, fleet.exact.canonical_json(sentinel) + "\n")
            archive.writestr(result_path, result_raw)
        raw = stream.getvalue()
        artifact_id = 50_000 + run_id
        self.archives[artifact_id] = raw
        self.artifacts[run_id] = {"id": artifact_id, "name": batch.artifact_name, "size_in_bytes": len(raw),
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "created_at": TIME,
            "expired": False, "workflow_run": {"id": run_id}}

    def api(self, endpoint, *, payload=None, **kwargs):
        self.calls.append((endpoint, deepcopy(payload)))
        result = self._api(endpoint, payload)
        return self.mutate(endpoint, deepcopy(result))

    def _api(self, endpoint, payload):
        prefix = f"repos/{REPOSITORY}"
        if endpoint == "rate_limit":
            return {"resources": {"core": {"limit": 5000, "remaining": self.remaining}}}
        if endpoint == prefix:
            return {"full_name": REPOSITORY, "private": False}
        if endpoint.startswith(prefix + "/git/ref/heads/"):
            branch = endpoint.split("/git/ref/heads/")[1]
            return {"ref": f"refs/heads/{branch}", "object": {"type": "commit",
                "sha": self.main_sha if branch == "main" else self.candidate_sha}}
        if "/actions/workflows/" in endpoint:
            match = re.search(r"test-all-packages-batch([0-9]+).yml", endpoint)
            batch = self.topology[int(match[1]) - 1]
            if endpoint.endswith("/dispatches"):
                self._new_run(batch, payload)
                if self.ambiguous_post:
                    raise fleet.ContractError("ambiguous dispatch response")
                return None
            if "/runs?" in endpoint:
                runs = [r for r in self.runs.values() if r["workflow_id"] == batch.batch]
                return {"total_count": len(runs), "workflow_runs": runs}
            return {"id": batch.batch, "path": batch.workflow_path, "name": batch.workflow_name, "state": "active"}
        if "/actions/runs/" in endpoint:
            run_id = int(endpoint.split("/actions/runs/")[1].split("/")[0])
            if "/jobs?" in endpoint:
                jobs = [j for j in self.jobs.values() if j["run_id"] == run_id]
                return {"total_count": len(jobs), "jobs": jobs}
            if "/artifacts?" in endpoint:
                return {"total_count": 1, "artifacts": [self.artifacts[run_id]]}
            run = deepcopy(self.runs[run_id])
            if self.pending:
                run.update(status="in_progress", conclusion=None)
            return run
        if "/actions/jobs/" in endpoint:
            return self.jobs[int(endpoint.split("/actions/jobs/")[1])]
        if "/actions/artifacts/" in endpoint:
            return self.archives[int(endpoint.split("/actions/artifacts/")[1].split("/")[0])]
        raise AssertionError(endpoint)


class FleetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        workflows = self.root / ".github/workflows"
        workflows.mkdir(parents=True)
        topology = []
        for batch, slug in enumerate(("alpha", "bravo"), 1):
            package = fleet.exact.PackageRegistration(f"test-{slug}", "test", f".github/workflows/test-{slug}.yml", slug)
            definition = fleet.exact.BatchDefinition(batch, f".github/workflows/test-all-packages-batch{batch}.yml",
                f"Test All Packages (Batch {batch}) on Arm64", f"batch{batch}-test-results", (package,), (), ())
            topology.append(definition)
            (self.root / package.workflow_path).write_text(package_source(slug))
            (self.root / definition.workflow_path).write_text(
                f"name: {definition.workflow_name}\njobs:\n  test-{slug}:\n    uses: ./.github/workflows/test-{slug}.yml\n"
                "\n  summary:\n    steps:\n      - name: Collect\n        id: collect\n        run: true\n"
                "      - name: Attest\n        id: attest\n        run: true\n"
                "      - name: Upload\n        uses: actions/upload-artifact@" + "c" * 40 + "\n")
        self.topology = tuple(topology)
        self.api = FakeAPI(self.topology)
        self.attestor = mock.Mock(side_effect=lambda descriptor, *a, **k: descriptor)
        self.options = {"repository_root": self.root, "bundle_receipt": {"candidate": DESCRIPTOR},
                        "attest_candidate": self.attestor}
        for name, value in (("validate_checkout_binding", BASE), ("discover_topology", self.topology)):
            patch = mock.patch.object(fleet.exact, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def worker(self, **options):
        options.setdefault("sleep", lambda _: None)
        return fleet.FleetValidation(self.api, wall_clock=lambda: EPOCH, **options)

    def run_fleet(self, **options):
        return self.worker(**options).run(DESCRIPTOR, **self.options)

    def assert_rejected(self, mutation):
        self.api.mutate = mutation
        with self.assertRaises((fleet.ContractError, fleet.exact.ContractError, fleet.batch_attestation.AttestationError)):
            self.run_fleet()

    def test_all_registered_batches_green_real_artifact_verifiers(self):
        receipt = self.run_fleet()
        self.assertEqual(receipt["status"], "success")
        self.assertFalse(receipt["publishing"])
        self.assertEqual(receipt["summary"]["package_count"], 2)
        self.assertEqual(receipt["summary"]["evidence_status"], "complete")
        self.assertEqual(len(receipt["attestation"]["batches"]), 2)
        self.assertEqual(self.attestor.call_count, 2)
        self.assertEqual(len([c for c in self.api.calls if c[1] is not None]), 2)
        self.assertTrue(all("/dispatches" in c[0] and "test-all-packages-batch" in c[0]
                            for c in self.api.calls if c[1] is not None))
        verified = self.worker().verify(DESCRIPTOR, receipt, **self.options)
        self.assertEqual(verified, receipt)
        self.assertEqual(self.attestor.call_count, 4)

    def test_one_failed_batch_gets_only_one_fresh_confirmation(self):
        self.api.failures = {1: [True, False]}
        receipt = self.run_fleet()
        self.assertEqual(receipt["status"], "success")
        self.assertEqual([len(h) for h in receipt["history"]], [2, 1])
        self.assertEqual(self.attestor.call_count, 2)
        first, second = receipt["history"][0]
        self.assertNotEqual(first["dispatch_nonce"], second["dispatch_nonce"])
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(receipt["summary"]["accepted_runs"][0]["run_id"], second["run_id"])
        self.assertEqual(self.worker().verify(DESCRIPTOR, receipt, **self.options), receipt)

    def test_persistent_failure_returns_complete_authentic_feedback(self):
        self.api.failures = {2: [True, True, True]}
        receipt = self.run_fleet()
        self.assertEqual(receipt["status"], "failure")
        self.assertEqual(receipt["summary"]["failed_batches"], [2])
        self.assertEqual(receipt["summary"]["failed_packages"][0]["package_slug"], "bravo")
        self.assertEqual(receipt["summary"]["evidence_status"], "complete")
        self.assertEqual([len(h) for h in receipt["history"]], [1, 2])
        self.assertEqual(self.worker().verify(DESCRIPTOR, receipt, **self.options), receipt)

    def test_unknown_version_can_describe_failure_but_never_success(self):
        self.api.failures = {1: [True, True]}
        receipt = self.run_fleet()
        history = receipt["history"][0][-1]
        run, job = history["record"]["run"], history["record"]["jobs"][0]
        registration = self.topology[0].packages[0]
        with zipfile.ZipFile(io.BytesIO(self.api.archives[history["record"]["artifact"]["id"]])) as archive:
            result = json.loads(archive.read("alpha-test-results/alpha.json"))
        result["package"]["version"] = "unknown"
        observed = fleet._failed_result(result, registration=registration, batch=1, run=run, job=job)
        self.assertEqual(observed["package"]["version"], "unknown")
        with self.assertRaises(fleet.ContractError):
            fleet._failed_result(result, registration=registration, batch=1, run=run, job=dict(job, conclusion="success"))
        with self.assertRaises(fleet.exact.ContractError):
            fleet.exact.validate_package_result(result, registration=registration, repository=REPOSITORY,
                                                batch=1, run=run, job=job)

    def test_no_missing_topology_authorization(self):
        self.attestor.side_effect = lambda d, *a, **k: dict(d, candidate_sha="e" * 40)
        with self.assertRaises(fleet.ContractError):
            self.run_fleet()
        self.assertFalse(any(c[1] is not None for c in self.api.calls))

    def test_current_main_and_candidate_ref_required(self):
        for field in ("main_sha", "candidate_sha"):
            with self.subTest(field=field):
                old = getattr(self.api, field)
                setattr(self.api, field, "f" * 40)
                with self.assertRaises(fleet.ContractError):
                    self.run_fleet()
                setattr(self.api, field, old)

    def test_main_advance_after_dispatch_aborts(self):
        def mutate(endpoint, result):
            if endpoint.endswith("/dispatches"):
                self.api.main_sha = "f" * 40
            return result
        self.assert_rejected(mutate)

    def test_private_repository_rejected_before_dispatch(self):
        self.assert_rejected(lambda endpoint, value: dict(value, private=True)
            if endpoint == f"repos/{REPOSITORY}" else value)

    def test_wrong_run_identity_matrix(self):
        for key, value in (("run_attempt", 2), ("head_sha", "c" * 40), ("head_branch", "main"),
                           ("event", "push"), ("path", ".github/workflows/evil.yml"),
                           ("workflow_id", 99), ("head_repository", {"full_name": "other/repo"}),
                           ("head_commit", {"id": BASE}), ("html_url", "https://evil.invalid"),
                           ("conclusion", "cancelled"), ("created_at", "2020-01-01T00:00:00Z")):
            with self.subTest(key=key):
                self.api.runs.clear()
                self.api.jobs.clear()
                self.assert_rejected(lambda e, v: dict(v, **{key: value})
                    if re.search(r"/actions/runs/\d+$", e) else v)

    def test_duplicate_registration_rejected(self):
        def mutate(endpoint, value):
            if "workflow_runs" in (value if isinstance(value, dict) else {}) and value["workflow_runs"]:
                value["workflow_runs"].append(dict(value["workflow_runs"][0], id=999999))
                value["total_count"] += 1
            return value
        self.assert_rejected(mutate)

    def test_wrong_runner_or_job_identity_rejected(self):
        mutations = (("labels", ["self-hosted", "arm64"]), ("runner_group_id", 1),
            ("runner_group_name", "internal"), ("head_sha", BASE), ("run_attempt", 2), ("run_id", 1),
            ("runner_id", 0), ("runner_name", ""), ("html_url", "https://evil.invalid"))
        for field, value in mutations:
            with self.subTest(field=field):
                self.api.runs.clear()
                self.api.jobs.clear()
                def mutate(e, payload):
                    if isinstance(payload, dict) and "jobs" in payload:
                        for j in payload["jobs"]:
                            if j["name"] != "summary":
                                j[field] = value
                    if re.search(r"/actions/jobs/\d+$", e) and payload["name"] != "summary":
                        payload[field] = value
                    return payload
                self.assert_rejected(mutate)

    def test_required_skipped_or_failed_step_cannot_be_green(self):
        for status in ("skipped", "failure"):
            with self.subTest(status=status):
                self.api.runs.clear()
                self.api.jobs.clear()
                def mutate(e, v):
                    for j in v.get("jobs", []) if isinstance(v, dict) else []:
                        if j["name"] != "summary":
                            j["steps"][1]["conclusion"] = status
                    if re.search(r"/actions/jobs/\d+$", e) and v["name"] != "summary":
                        v["steps"][1]["conclusion"] = status
                    return v
                self.assert_rejected(mutate)

    def test_missing_package_job_rejected(self):
        self.assert_rejected(lambda e, v: {"total_count": 1, "jobs": v["jobs"][1:]}
            if "/jobs?" in e else v)

    def test_artifact_identity_and_integrity_rejected(self):
        for field, value in (("expired", True), ("digest", "sha256:" + "0" * 64),
                              ("size_in_bytes", 1), ("workflow_run", {"id": 99})):
            with self.subTest(field=field):
                self.api.runs.clear()
                self.api.jobs.clear()
                def mutate(e, v):
                    if "/artifacts?" in e:
                        v["artifacts"][0][field] = value
                    return v
                self.assert_rejected(mutate)

    def test_missing_artifact_is_not_admissible_feedback(self):
        self.api.failures = {1: [True, True]}
        self.assert_rejected(lambda e, v: {"total_count": 0, "artifacts": []} if "/artifacts?" in e else v)

    def tamper_archive(self, transform):
        def mutate(endpoint, value):
            if "/artifacts?" in endpoint:
                artifact = value["artifacts"][0]
                with zipfile.ZipFile(io.BytesIO(self.api.archives[artifact["id"]])) as source:
                    members = {name: source.read(name) for name in source.namelist()}
                transform(members)
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as target:
                    for name, raw in members.items():
                        target.writestr(name, raw)
                raw = stream.getvalue()
                self.api.archives[artifact["id"]] = raw
                artifact["digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
                artifact["size_in_bytes"] = len(raw)
            return value
        self.assert_rejected(mutate)

    def test_attestation_exact_binding_matrix(self):
        for field, value in (("expected_sha", BASE), ("branch", "main"), ("dispatch_nonce", "0" * 64),
                              ("run_id", 999), ("run_attempt", 2), ("repository", "other/repo")):
            with self.subTest(field=field):
                self.api.runs.clear()
                self.api.jobs.clear()
                def transform(members):
                    name = fleet.batch_attestation.SENTINEL_NAME
                    payload = json.loads(members[name])
                    payload[field] = value
                    members[name] = (fleet.exact.canonical_json(payload) + "\n").encode()
                self.tamper_archive(transform)

    def test_malicious_archive_paths_and_extra_files_rejected(self):
        for path in ("../escape", "/absolute", "unexpected.txt", "alpha-test-results/other.json"):
            with self.subTest(path=path):
                self.api.runs.clear()
                self.api.jobs.clear()
                self.tamper_archive(lambda members: members.update({path: b"bad"}))

    def test_required_package_result_cannot_be_faked_as_skipped(self):
        def transform(members):
            sentinel = json.loads(members[fleet.batch_attestation.SENTINEL_NAME])
            package = sentinel["packages"][0]
            result = json.loads(members[package["result_path"]])
            result["tests"]["details"][0]["status"] = "skipped"
            result["tests"]["passed"] -= 1
            result["tests"]["skipped"] += 1
            raw = (fleet.exact.canonical_json(result) + "\n").encode()
            package["sha256"] = hashlib.sha256(raw).hexdigest()
            members[package["result_path"]] = raw
            members[fleet.batch_attestation.SENTINEL_NAME] = (fleet.exact.canonical_json(sentinel) + "\n").encode()
        self.tamper_archive(transform)

    def test_failed_producer_step_cannot_authenticate_artifact(self):
        def mutate(endpoint, value):
            if "/jobs?" in endpoint:
                summary = next(j for j in value["jobs"] if j["name"] == "summary")
                summary["steps"][-1]["conclusion"] = "skipped"
            return value
        self.assert_rejected(mutate)

    def test_inventory_truncation_and_duplicate_ids_rejected(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                self.api.runs.clear()
                self.api.jobs.clear()
                def mutate(endpoint, value):
                    if "/jobs?" in endpoint:
                        if duplicate:
                            value["jobs"][1]["id"] = value["jobs"][0]["id"]
                        else:
                            value["total_count"] += 1
                    return value
                self.assert_rejected(mutate)

    def test_required_step_name_and_number_must_match_trusted_base(self):
        for field, value in (("name", "different test"), ("number", 99)):
            with self.subTest(field=field):
                self.api.runs.clear()
                self.api.jobs.clear()
                def mutate(endpoint, payload):
                    if "/jobs?" in endpoint:
                        payload["jobs"][0]["steps"][1][field] = value
                    return payload
                self.assert_rejected(mutate)

    def test_final_verification_rejects_new_candidate_run(self):
        receipt = self.run_fleet()
        extra = deepcopy(next(iter(self.api.runs.values())))
        extra["id"] = 99999
        self.api.runs[extra["id"]] = extra
        with self.assertRaises(fleet.ContractError):
            self.worker().verify(DESCRIPTOR, receipt, **self.options)

    def test_receipt_expires_without_reinterpreting_as_green(self):
        receipt = self.run_fleet()
        worker = fleet.FleetValidation(self.api, wall_clock=lambda: EPOCH + 86401)
        with self.assertRaises(fleet.ContractError):
            worker.verify(DESCRIPTOR, receipt, **self.options)

    def test_cli_writes_verified_failure_then_allows_parent_separate_gate(self):
        self.api.failures = {1: [True, True]}
        receipt = self.run_fleet()
        descriptor_path, bundle_path = self.root / "descriptor.json", self.root / "bundle.json"
        descriptor_path.write_text(json.dumps(DESCRIPTOR))
        bundle_path.write_text("{}")
        environment = {"GITHUB_REPOSITORY": REPOSITORY, "GITHUB_REF": "refs/heads/main",
                       "GITHUB_SHA": BASE, "GITHUB_RUN_ATTEMPT": "1"}
        with mock.patch.dict("os.environ", environment, clear=True), mock.patch.object(
                fleet.FleetValidation, "run", return_value=receipt), mock.patch("sys.stdout", new_callable=io.StringIO):
            exit_code = fleet.main(["run", "--descriptor", str(descriptor_path), "--bundle-receipt", str(bundle_path),
                "--repository-root", str(self.root), "--output-dir", str(self.root / "output")])
        self.assertEqual(exit_code, 0)
        observed = json.loads((self.root / "output/receipt.json").read_text())
        self.assertEqual(observed["status"], "failure")
        self.assertFalse(observed["publishing"])

    def test_ambiguous_post_is_not_repeated(self):
        self.api.ambiguous_post = True
        worker = self.worker()
        with self.assertRaises(fleet.ContractError):
            worker.run(DESCRIPTOR, **self.options)
        self.assertEqual(len([c for c in self.api.calls if c[1] is not None]), 1)
        with self.assertRaises(fleet.ContractError):
            worker.run(DESCRIPTOR, **self.options)
        self.assertEqual(len([c for c in self.api.calls if c[1] is not None]), 1)

    def test_prior_candidate_run_blocks_new_worker(self):
        self.run_fleet()
        before = len([c for c in self.api.calls if c[1] is not None])
        with self.assertRaises(fleet.ContractError):
            self.run_fleet()
        self.assertEqual(len([c for c in self.api.calls if c[1] is not None]), before)

    def test_low_rate_quota_no_dispatch(self):
        self.api.remaining = 219
        with self.assertRaises(fleet.ContractError):
            self.run_fleet()
        self.assertFalse(any(c[1] is not None for c in self.api.calls))

    def test_timeout_request_and_poll_budgets_fail_closed(self):
        with self.assertRaises(fleet.ContractError):
            self.run_fleet(max_requests=1)
        self.api.pending = True
        with self.assertRaises(fleet.ContractError):
            self.run_fleet(max_polls=1, sleep=lambda _: None)
        worker = self.worker(clock=lambda: 0)
        worker.clock = lambda: fleet.MAX_SECONDS + 1
        with self.assertRaises(fleet.ContractError):
            worker.remaining()

    def test_tampered_receipt_never_authorizes_success(self):
        receipt = self.run_fleet()
        for mutation in (lambda r: r.update(publishing=True),
                         lambda r: r["summary"].update(package_count=1),
                         lambda r: r["history"].pop(),
                         lambda r: r["history"][0][0].update(run_id=42),
                         lambda r: r["attestation"].update(overall_status="failure"),
                         lambda r: r.update(topology_sha256="0" * 64),
                         lambda r: r["descriptor"].update(candidate_sha=BASE)):
            candidate = deepcopy(receipt)
            mutation(candidate)
            with self.assertRaises((fleet.ContractError, fleet.exact.ContractError)):
                self.worker().verify(DESCRIPTOR, candidate, **self.options)

    def test_attempt_advances_during_final_recheck_rejected(self):
        def mutate(endpoint, value):
            if re.search(r"/actions/runs/\d+$", endpoint) and any("/zip" in c[0] for c in self.api.calls):
                value["run_attempt"] = 2
            return value
        self.assert_rejected(mutate)

    def test_no_model_or_log_metadata_exported(self):
        def mutate(endpoint, value):
            if isinstance(value, dict) and ("/actions/runs/" in endpoint or "/actions/workflows/" in endpoint):
                value["private_provider_metadata"] = "secret-canary"
            return value
        self.api.mutate = mutate
        receipt = self.run_fleet()
        self.assertNotIn("secret-canary", json.dumps(receipt))
        self.assertFalse(any("/logs" in c[0] for c in self.api.calls))


class ContractTests(unittest.TestCase):
    def test_all_current_package_workflows_have_a_derived_required_probe_contract(self):
        root = Path(__file__).resolve().parents[3]
        topology = fleet.exact.discover_topology(root)
        count = 0
        for batch in topology:
            for package in batch.packages:
                with self.subTest(package=package.package_slug):
                    contract = fleet._required_steps((root / package.workflow_path).read_bytes(), package)
                    self.assertGreaterEqual(len(contract["required"]), 5)
                    count += 1
        self.assertEqual(count, 960)

    def test_descriptor_exact_schema_and_scope(self):
        self.assertEqual(fleet.validate_descriptor(DESCRIPTOR), DESCRIPTOR)
        for field, value in (("schema_version", True), ("iteration", 4), ("iteration", True),
                             ("branch", "main"), ("candidate_sha", BASE), ("cycle_id", "oops"),
                             ("repository", "private/project"), ("model_token", "forbidden")):
            with self.subTest(field=field), self.assertRaises(fleet.ContractError):
                fleet.validate_descriptor(dict(DESCRIPTOR, **{field: value}))

    def test_composite_probe_names_and_unnamed_gate_supported(self):
        package = fleet.exact.PackageRegistration("test-alpha", "test", ".github/workflows/test-alpha.yml", "alpha")
        source = re.sub(r"        id: test[1-6]\n", "", package_source("alpha"))
        source = source.replace("      - name: Enforce failure status\n        if:", "      - if:")
        source = source.replace("run: exit 0", "run: test '${{ steps.summary.outputs.should_fail }}' != 1")
        contract = fleet._required_steps(source.encode(), package)
        self.assertEqual(len(contract["required"]), 6)
        self.assertIsNone(contract["gate"]["name"])

    def test_invalid_budget_rejected(self):
        for value in (0, -1, float("inf"), float("nan"), True):
            with self.subTest(value=value), self.assertRaises(fleet.ContractError):
                fleet.FleetValidation(timeout_seconds=value)

    def test_cli_requires_trusted_main_and_hides_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "descriptor.json").write_text(json.dumps(DESCRIPTOR))
            (root / "bundle.json").write_text("{}")
            argv = ["run", "--descriptor", str(root / "descriptor.json"), "--bundle-receipt", str(root / "bundle.json"),
                    "--repository-root", str(root), "--output-dir", str(root / "output")]
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(fleet.main(argv), 1)
                self.assertEqual(json.loads(stderr.getvalue()), {"status": "incomplete", "publishing": False})


if __name__ == "__main__":
    unittest.main()
