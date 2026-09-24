from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import orchestration_contract as contract
import smoke_recovery_incident as incident
import test_smoke_recovery as fixtures

REPO, SHA = fixtures.REPOSITORY, fixtures.SHA
RUN = 123456
BOT = "github-actions[bot]"
REPAIR_BOT = "dashboard-repair[bot]"
RECIPIENT = "smoke-owner"
SUMMARY = 555555


def steps(names):
    return [{"number": n, "name": name, "status": "completed", "conclusion": "success"}
            for n, name in enumerate(names, 1)]


def job(run, name, job_id, required=()):
    return {"id": job_id, "name": name, "run_id": run["id"], "run_attempt": run["run_attempt"],
            "head_sha": run["head_sha"], "status": "completed", "conclusion": "success",
            "started_at": run["created_at"], "completed_at": run["updated_at"],
            "html_url": f"https://github.com/{REPO}/actions/runs/{run['id']}/job/{job_id}",
            "steps": steps(required or ("Required check",))}


class FakeGitHub:
    """Exercise real controller/validators, with only transport and Git topology fake."""

    def __init__(self, success=False):
        self.calls, self.writes = [], []
        self.ref = fixtures.branch_ref()
        self.manifest = fixtures.initial_manifest()
        self.parent = {
            "id": RUN, "run_attempt": 1, "head_sha": SHA, "head_branch": "main",
            "path": incident.ORCHESTRATOR_PATH, "event": "schedule",
            "repository": {"full_name": REPO}, "head_repository": {"full_name": REPO},
            "created_at": "2026-09-11T11:50:00Z", "updated_at": "2026-09-11T12:31:00Z",
            "status": "completed", "conclusion": "success" if success else "failure",
        }
        self.parent_job = job(self.parent, incident.ORCHESTRATOR_JOB, 91, incident.PARENT_STEPS)
        self.parent_job["conclusion"] = self.parent["conclusion"]
        self.scope_job = job(self.parent, "Check smoke change scope", 92,
                             ("Check out exact main commit", "Classify authenticated changes"))
        self.runs = {RUN: self.parent}
        self.jobs = {RUN: [self.parent_job, self.scope_job]}
        for record in self.manifest["batches"]:
            self.runs[record["run_id"]] = fixtures.run_payload(record)
            self.jobs[record["run_id"]] = [fixtures.job_payload(record), fixtures.job_payload(record, summary=True)]
        self.summary = {**self.parent, "id": SUMMARY, "run_attempt": 1,
                        "name": contract.SUMMARY_WORKFLOW_NAME,
                        "path": contract.SUMMARY_WORKFLOW_PATH, "event": "workflow_dispatch",
                        "display_title": contract.expected_summary_run_name(fixtures.ORCHESTRATION, "f" * 64),
                        "created_at": "2026-09-11T12:05:00Z", "updated_at": "2026-09-11T12:20:00Z",
                        "status": "completed", "conclusion": "success"}
        self.runs[SUMMARY] = self.summary
        self.jobs[SUMMARY] = [job(self.summary, "Generate Global Summary", 93, incident.SUMMARY_STEPS),
                              job(self.summary, "Open generated test-results draft PR", 94,
                                  ("Open or update aggregated test-results review PR",))]
        self.audit = {"status": "batches_passed_summary_pending", "accepted_manifest": self.manifest}
        self.archive, self.artifact = None, None
        self.pack_audit()
        self.issue = None
        self.extra_issues = []
        self.pulls = []
        self.extra_runs = []
        self.listed_parents = None
        self.summary_extra = []
        self.private = False
        self.viewer = BOT
        self.assignable = True
        self.ignore_assignment = False
        self.hook = None

    def pack_audit(self, *, nonce=None, manifest=None, registered=None, summary=None, omit=None):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("recovery-audit.json", json.dumps(self.audit))
            members = {"summary-dispatch-nonce": nonce if nonce is not None else "f" * 64,
                       "run-manifest.json": json.dumps(manifest if manifest is not None else self.manifest),
                       "summary-run.json": json.dumps(summary if summary is not None else self.summary),
                       "summary-registration.json": json.dumps(registered if registered is not None else
                            [{"total_count": 1, "workflow_runs": [self.summary]}])}
            for name, data in members.items():
                if name != omit:
                    archive.writestr(name, data)
        self.archive = out.getvalue()
        self.artifact = {"id": 678, "name": f"smoke-orchestration-evidence-{RUN}-1", "expired": False,
                         "workflow_run": {"id": RUN, "head_sha": SHA, "head_branch": "main"},
                         "size_in_bytes": len(self.archive), "digest": "sha256:" + hashlib.sha256(self.archive).hexdigest(),
                         "created_at": "2026-09-11T12:30:00Z"}

    def state(self, status="needs_investigation"):
        return {"schema": 1, "repository": REPO, "status": status, "reason": "full_main_failed",
                "runs": [incident._run_record(self.parent)], "pull_requests": []}

    def set_issue(self, state=None):
        self.issue = {"id": "I_123", "number": 9, "title": incident.TITLE,
                      "body": incident.render(state or self.state()), "state": "OPEN",
                      "updatedAt": "2026-09-11T13:00:00Z", "lastEditedAt": None,
                      "author": {"login": BOT}, "editor": None,
                      "repository": {"nameWithOwner": REPO}}

    def add_pull(self, number=88, merged=False):
        branch = f"automation/smoke-repair/{RUN}-1-nginx"
        pull = {"id": number + 100, "number": number, "state": "closed" if merged else "open", "merged": merged,
                "head": {"ref": branch, "sha": "c" * 40, "repo": {"full_name": REPO}},
                "base": {"ref": "main", "repo": {"full_name": REPO}},
                "user": {"login": REPAIR_BOT, "type": "Bot"},
                "body": f"<!-- smoke-repair:{RUN}-1-nginx:v1 -->\nother content not copied",
                "html_url": f"https://github.com/{REPO}/pull/{number}"}
        self.pulls.append(pull)
        return pull

    def api(self, endpoint, *, payload=None, raw=False, timeout=60):
        self.calls.append((endpoint, deepcopy(payload)))
        if self.hook:
            self.hook(endpoint, payload)
        path = urlsplit(endpoint).path
        query = parse_qs(urlsplit(endpoint).query)
        root = f"repos/{REPO}"

        def page(items, key=None):
            start = (int(query.get("page", [1])[0]) - 1) * 100
            selected = deepcopy(items[start:start + 100])
            return {"total_count": len(items), key: selected} if key else selected

        if path == root:
            return {"full_name": REPO, "private": self.private}
        if path == root + "/git/ref/heads/main":
            return deepcopy(self.ref)
        if path.startswith(root + "/assignees/"):
            if not self.assignable:
                raise contract.ContractError("GitHub API request failed; no evidence inferred")
            self.assert_assignment_read = raw
            return b""
        if path == root + "/issues":
            if payload is not None:
                self.writes.append((path, payload))
                self.set_issue(incident.parse(payload["body"], REPO))
                assignees = [] if self.ignore_assignment else [{"login": login, "type": "User"} for login in payload.get("assignees", [])]
                return {"number": 9, "assignees": assignees}
            values = deepcopy(self.extra_issues)
            if self.issue:
                values.append({"id": 900, "number": 9, "title": self.issue["title"], "body": self.issue["body"],
                               "user": {"login": self.issue["author"]["login"], "type": "Bot"}})
            return page(values)
        if path == "graphql":
            if payload["query"] == "query { viewer { login } }":
                return {"data": {"viewer": {"login": self.viewer}}}
            if payload["query"].startswith("mutation"):
                self.writes.append((path, payload))
                self.issue.update(body=payload["variables"]["input"]["body"], state=payload["variables"]["input"]["state"],
                                  lastEditedAt="2026-09-11T13:01:00Z", editor={"login": BOT})
                return {"data": {"updateIssue": {"issue": deepcopy(self.issue)}}}
            return {"data": {"repository": {"issue": deepcopy(self.issue)}}}
        if path == root + "/pulls":
            return page(self.pulls)
        if path.startswith(root + "/pulls/"):
            return deepcopy(next(p for p in self.pulls if p["number"] == int(path.rsplit("/", 1)[1])))
        if path.endswith("/workflows/test-all-packages-orchestrator.yml/runs"):
            return page(([self.parent] + self.extra_runs) if self.listed_parents is None else self.listed_parents, "workflow_runs")
        if path.endswith("/workflows/test-all-packages-summary.yml/runs"):
            return page([self.summary] + self.summary_extra, "workflow_runs")
        if path == root + "/actions/artifacts/678":
            return deepcopy(self.artifact)
        if path == root + "/actions/artifacts/678/zip":
            return self.archive
        if path.startswith(root + "/actions/runs/"):
            suffix = path.removeprefix(root + "/actions/runs/").split("/")
            run_id = int(suffix[0])
            if len(suffix) == 1:
                return deepcopy(self.runs[run_id])
            if len(suffix) == 3 and suffix[1] == "attempts":
                return deepcopy(self.runs[run_id])
            if suffix[-1] == "jobs":
                if int(suffix[2]) != self.runs[run_id]["run_attempt"]:
                    raise AssertionError("controller fetched the wrong run attempt")
                return page(self.jobs[run_id], "jobs")
            if suffix[-1] == "artifacts":
                return page([self.artifact], "artifacts")
        raise AssertionError((endpoint, payload))


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGitHub()
        self.topology = mock.patch.object(incident, "discover_topology_at_commit", return_value=tuple(fixtures.definition(b) for b in range(1, 23)))
        self.topology.start()
        self.addCleanup(self.topology.stop)

    def sync(self, **kwargs):
        kwargs.setdefault("recipient", RECIPIENT)
        return incident.sync(repository=REPO, run_id=RUN, run_attempt=1, expected_sha=SHA,
                             repository_root=Path("."), api=self.fake, **kwargs)

    def test_failure_creates_one_issue_and_repeat_is_idempotent(self):
        first = self.sync(write=True)
        self.assertEqual(first["status"], "needs_investigation")
        self.assertTrue(first["written"])
        self.assertFalse(self.sync(write=True)["written"])
        self.assertEqual(len(self.fake.writes), 1)
        self.assertEqual(self.fake.writes[0][1]["assignees"], [RECIPIENT])
        self.assertEqual(first["assigned_to"], RECIPIENT)
        self.assertNotIn(RECIPIENT, self.fake.issue["body"])
        self.assertEqual(incident.parse(self.fake.issue["body"], REPO), self.fake.state())

    def test_missing_or_invalid_recipient_cannot_create_issue(self):
        for recipient in (None, "", "@owner", "owner/name", "owner\n@other", "owner_name",
                          "-owner", "owner-", "owner--name", "x" * 40, "bot[bot]", "own\u00e9r", [RECIPIENT]):
            with self.subTest(recipient=recipient):
                self.fake = FakeGitHub()
                with self.assertRaisesRegex(contract.ContractError, "human GitHub login"):
                    self.sync(recipient=recipient, write=True)
                self.assertFalse(self.fake.writes)

    def test_unassignable_recipient_blocks_creation(self):
        self.fake.assignable = False
        with self.assertRaises(contract.ContractError):
            self.sync(write=True)
        self.assertFalse(self.fake.writes)

    def test_silently_ignored_assignment_is_not_reported_as_success(self):
        self.fake.ignore_assignment = True
        with self.assertRaisesRegex(contract.ContractError, "assignment was not confirmed"):
            self.sync(write=True)
        self.assertEqual(len(self.fake.writes), 1)

    def test_existing_issue_update_does_not_reassign_or_change_canonical_schema(self):
        self.fake.set_issue()
        self.fake.add_pull()
        self.sync(repair_bot=REPAIR_BOT, recipient=None, write=True)
        self.assertEqual(len(self.fake.writes), 1)
        self.assertNotIn("assignees", self.fake.writes[0][1]["variables"]["input"])
        self.assertFalse(any("/assignees/" in path for path, _ in self.fake.calls))

    def test_read_only_default_never_mutates(self):
        self.assertFalse(self.sync()["written"])
        self.assertEqual(self.fake.writes, [])

    def test_human_token_cannot_create_or_update_issue(self):
        self.fake.viewer = "maintainer"
        with self.assertRaisesRegex(contract.ContractError, "configured bot"):
            self.sync(write=True)
        self.assertEqual(self.fake.writes, [])

    def test_live_full_fleet_and_summary_close_existing_incident(self):
        self.fake = FakeGitHub(success=True)
        self.fake.set_issue()
        result = self.sync(write=True)
        self.assertEqual(result["status"], "verified_green")
        self.assertEqual(result["summary_run_id"], SUMMARY)
        self.assertEqual(self.fake.issue["state"], "CLOSED")
        self.assertEqual(len(self.fake.writes), 1)
        self.assertTrue(all(any(f"/{10000 + b}/attempts/1/jobs" in path for path, _ in self.fake.calls) for b in range(1, 23)))

    def test_success_without_incident_does_not_create_closed_issue(self):
        self.fake = FakeGitHub(success=True)
        self.assertEqual(self.sync(write=True)["status"], "verified_green")
        self.assertEqual(self.fake.writes, [])

    def test_optional_step_skip_is_not_claimed_as_a_pass(self):
        self.fake = FakeGitHub(success=True)
        self.fake.jobs[10001][0]["steps"].append({"number": 2, "name": "Optional check",
                                               "status": "completed", "conclusion": "skipped"})
        self.fake.set_issue()
        result = self.sync(write=True)
        self.assertEqual(result["status"], "verified_green")
        self.assertEqual(result["verification_scope"], "required_package_jobs_and_exact_summary")
        self.assertEqual(result["optional_skips"], "not_counted_as_passes")
        self.assertIn("remain skips, not passes", self.fake.issue["body"])

    def test_open_bot_repair_is_pending_review_not_green(self):
        self.fake.add_pull()
        result = self.sync(repair_bot=REPAIR_BOT, write=True)
        self.assertEqual(result["status"], "pending_manual_review")
        self.assertIn(88, incident.parse(self.fake.issue["body"], REPO)["pull_requests"])

    def test_merged_pr_does_not_establish_green(self):
        self.fake.add_pull(merged=True)
        self.assertEqual(self.sync(repair_bot=REPAIR_BOT)["status"], "needs_investigation")

    def test_foreign_pr_or_wrong_marker_is_rejected(self):
        for change in (lambda p: p["user"].update(login="someone"),
                       lambda p: p["head"]["repo"].update(full_name="foreign/repo"),
                       lambda p: p.update(body="<!-- smoke-repair:wrong:v1 -->"),
                       lambda p: p["base"].update(ref="production"),
                       lambda p: p.update(html_url="https://untrusted.example/pr")):
            with self.subTest(change=change):
                self.fake = FakeGitHub()
                change(self.fake.add_pull())
                with self.assertRaises(contract.ContractError):
                    self.sync(repair_bot=REPAIR_BOT, write=True)
                self.assertEqual(self.fake.writes, [])

    def test_main_advanced_keeps_incident_open(self):
        self.fake = FakeGitHub(success=True)
        self.fake.ref = fixtures.branch_ref(fixtures.OTHER_SHA)
        result = self.sync(write=True)
        self.assertEqual(result["status"], "awaiting_full_main")
        self.assertEqual(self.fake.issue["state"], "OPEN")

    def test_newer_same_sha_run_cannot_be_ignored(self):
        self.fake = FakeGitHub(success=True)
        newer = {**self.fake.parent, "id": RUN + 1, "created_at": "2026-09-11T12:40:00Z"}
        self.fake.extra_runs.append(newer)
        with self.assertRaisesRegex(contract.ContractError, "supersedes"):
            self.sync(write=True)
        self.assertEqual(self.fake.writes, [])

    def test_stale_event_cannot_overwrite_newer_incident(self):
        state = self.fake.state()
        state["runs"][0].update(id=RUN + 1, created_at="2026-09-11T14:00:00Z")
        self.fake.runs[RUN + 1] = {**self.fake.parent, "id": RUN + 1, "created_at": "2026-09-11T14:00:00Z", "updated_at": "2026-09-11T15:00:00Z"}
        self.fake.set_issue(state)
        self.assertEqual(self.sync(write=True)["status"], "stale_event_ignored")
        self.assertEqual(self.fake.writes, [])

    def test_parent_identity_tampering_rejected(self):
        for key, value in (("id", RUN + 1), ("run_attempt", 2), ("head_sha", "b" * 40),
                           ("head_branch", "production"), ("path", ".github/workflows/test-nginx.yml"),
                           ("event", "pull_request"), ("status", "in_progress"), ("conclusion", None),
                           ("repository", {"full_name": "foreign/repo"}), ("id", True)):
            with self.subTest(key=key, value=value):
                self.fake = FakeGitHub()
                self.fake.parent[key] = value
                with self.assertRaises(contract.ContractError):
                    self.sync(write=True)
                self.assertEqual(self.fake.writes, [])

    def test_duplicate_or_foreign_issue_rejected(self):
        self.fake.set_issue()
        self.fake.extra_issues.append({"id": 901, "number": 10, "title": incident.TITLE, "body": ""})
        with self.assertRaisesRegex(contract.ContractError, "multiple"):
            self.sync(write=True)
        self.fake.extra_issues.clear()
        self.fake.issue["author"]["login"] = "someone"
        with self.assertRaises(contract.ContractError):
            self.sync(write=True)

    def test_human_edit_and_noncanonical_body_rejected(self):
        self.fake.set_issue()
        self.fake.issue.update(lastEditedAt="2026-09-11T13:01:00Z", editor={"login": "maintainer"})
        with self.assertRaisesRegex(contract.ContractError, "edited"):
            self.sync(write=True)
        self.fake.set_issue()
        self.fake.issue["body"] += "\nAll tests passed!"
        with self.assertRaises(contract.ContractError):
            self.sync(write=True)
        self.assertEqual(self.fake.writes, [])

    def test_issue_body_green_never_substitutes_for_run(self):
        self.fake.set_issue(self.fake.state("verified_green"))
        self.fake.issue["state"] = "CLOSED"
        result = self.sync(write=True)
        self.assertEqual(result["status"], "needs_investigation")
        self.assertEqual(self.fake.issue["state"], "OPEN")

    def test_new_failed_run_updates_same_issue_and_preserves_prior_failure(self):
        state = self.fake.state()
        state["runs"][0].update(id=RUN - 1, sha="d" * 40, created_at="2026-09-10T12:00:00Z")
        self.fake.runs[RUN - 1] = {**self.fake.parent, "id": RUN - 1, "head_sha": "d" * 40, "created_at": "2026-09-10T12:00:00Z"}
        self.fake.set_issue(state)
        result = self.sync(write=True)
        self.assertEqual(result["issue"], 9)
        self.assertEqual([r["id"] for r in incident.parse(self.fake.issue["body"], REPO)["runs"]], [RUN - 1, RUN])
        self.assertEqual(len(self.fake.writes), 1)

    def test_closed_prior_episode_reopens_with_new_bounded_journal(self):
        state = self.fake.state("verified_green")
        state["runs"][0].update(id=RUN - 1, created_at="2026-09-10T12:00:00Z")
        self.fake.runs[RUN - 1] = {**self.fake.parent, "id": RUN - 1, "created_at": "2026-09-10T12:00:00Z"}
        self.fake.set_issue(state)
        self.fake.issue["state"] = "CLOSED"
        self.sync(write=True)
        self.assertEqual(self.fake.issue["state"], "OPEN")
        self.assertEqual(len(incident.parse(self.fake.issue["body"], REPO)["runs"]), 1)

    def test_tampered_journal_anchor_sha_attempt_and_time_rejected(self):
        for key, value in (("sha", "b" * 40), ("attempt", 2), ("created_at", "2026-09-11T14:00:00Z")):
            with self.subTest(key=key):
                state = self.fake.state()
                state["runs"][0][key] = value
                self.fake.set_issue(state)
                with self.assertRaises(contract.ContractError):
                    self.sync(write=True)
                self.assertFalse(self.fake.writes)

    def test_required_gate_names_match_repository_workflows(self):
        root = Path(__file__).resolve().parents[3]
        parent = fixtures.yaml.safe_load((root / incident.ORCHESTRATOR_PATH).read_text())
        summary = fixtures.yaml.safe_load((root / contract.SUMMARY_WORKFLOW_PATH).read_text())
        parent_steps = {s.get("name") for s in parent["jobs"]["orchestrate-batches"]["steps"]}
        summary_steps = {s.get("name") for s in summary["jobs"]["global-summary"]["steps"]}
        self.assertTrue(set(incident.PARENT_STEPS).issubset(parent_steps))
        self.assertTrue(set(incident.SUMMARY_STEPS).issubset(summary_steps))

    def test_failed_missing_skipped_batch_jobs_never_green(self):
        for mutation in (lambda jobs: jobs.pop(), lambda jobs: jobs[0].update(conclusion="failure"),
                         lambda jobs: jobs[0].update(conclusion="skipped"), lambda jobs: jobs.append(deepcopy(jobs[0])),
                         lambda jobs: jobs[0].update(run_attempt=2), lambda jobs: jobs[0].update(head_sha="b" * 40)):
            with self.subTest(mutation=mutation):
                self.fake = FakeGitHub(success=True)
                mutation(self.fake.jobs[10001])
                with self.assertRaises(ValueError):
                    self.sync(write=True)
                self.assertEqual(self.fake.writes, [])

    def test_failed_skipped_missing_parent_summary_steps_never_green(self):
        for target in ("parent", "summary"):
            for conclusion in ("failure", "skipped", "cancelled", None):
                with self.subTest(target=target, conclusion=conclusion):
                    self.fake = FakeGitHub(success=True)
                    selected = self.fake.parent_job if target == "parent" else self.fake.jobs[SUMMARY][0]
                    selected["steps"][0]["conclusion"] = conclusion
                    with self.assertRaises(ValueError):
                        self.sync(write=True)
                    self.assertEqual(self.fake.writes, [])

    def test_summary_requires_both_required_jobs(self):
        for conclusion in ("failure", "skipped", "cancelled"):
            self.fake = FakeGitHub(success=True)
            self.fake.jobs[SUMMARY][1]["conclusion"] = conclusion
            with self.assertRaises(contract.ContractError):
                self.sync(write=True)
        self.fake = FakeGitHub(success=True)
        self.fake.jobs[SUMMARY].pop()
        with self.assertRaises(contract.ContractError):
            self.sync(write=True)

    def test_summary_nonce_branch_attempt_or_duplicate_rejected(self):
        for key, value in (("head_branch", "other"), ("run_attempt", 2), ("conclusion", "failure"),
                           ("display_title", "Global Summary [wrong] [nonce:" + "f" * 64 + "]")):
            self.fake = FakeGitHub(success=True)
            self.fake.summary[key] = value
            with self.assertRaises(contract.ContractError):
                self.sync(write=True)
        self.fake = FakeGitHub(success=True)
        self.fake.summary_extra.append({**self.fake.summary, "id": SUMMARY + 1})
        with self.assertRaises(contract.ContractError):
            self.sync(write=True)

    def test_tampered_expired_or_wrong_attempt_artifact_rejected(self):
        for key, value in (("expired", True), ("digest", "sha256:" + "0" * 64),
                           ("name", f"smoke-orchestration-evidence-{RUN}-2"),
                           ("workflow_run", {"id": RUN + 1, "head_sha": SHA, "head_branch": "main"})):
            self.fake = FakeGitHub(success=True)
            self.fake.artifact[key] = value
            with self.assertRaises(contract.ContractError):
                self.sync(write=True)

    def test_wrong_or_incomplete_manifest_never_green(self):
        for mutate in (lambda m: m.update(expected_sha="b" * 40), lambda m: m["batches"].pop(),
                       lambda m: m.update(orchestration_id="orchestration-999-1")):
            self.fake = FakeGitHub(success=True)
            mutate(self.fake.manifest)
            self.fake.pack_audit()
            with self.assertRaises(contract.ContractError):
                self.sync(write=True)

    def test_captured_summary_nonce_registration_and_manifest_cannot_be_substituted(self):
        for options in ({"nonce": "a" * 64}, {"nonce": "f" * 64 + "\n"},
                        {"registered": [{"total_count": 0, "workflow_runs": []}]},
                        {"registered": [{"total_count": 2, "workflow_runs": [self.fake.summary, self.fake.summary]}]},
                        {"manifest": {**self.fake.manifest, "expected_sha": "b" * 40}},
                        {"summary": {**self.fake.summary, "id": SUMMARY + 1}},
                        {"summary": {**self.fake.summary, "conclusion": "failure"}},
                        {"omit": "summary-dispatch-nonce"}, {"omit": "summary-registration.json"},
                        {"omit": "summary-run.json"}, {"omit": "run-manifest.json"}):
            with self.subTest(options=options):
                self.fake = FakeGitHub(success=True)
                self.fake.pack_audit(**options)
                with self.assertRaises(contract.ContractError):
                    self.sync(write=True)
                self.assertFalse(self.fake.writes)

    def test_live_summary_with_different_nonce_cannot_replace_captured_summary(self):
        self.fake = FakeGitHub(success=True)
        self.fake.summary["display_title"] = contract.expected_summary_run_name(fixtures.ORCHESTRATION, "e" * 64)
        with self.assertRaises(contract.ContractError):
            self.sync(write=True)
        self.assertFalse(self.fake.writes)

    def test_issue_change_race_prevents_write(self):
        self.fake.set_issue()
        self.fake.add_pull()
        reads = 0

        def race(endpoint, payload):
            nonlocal reads
            if endpoint == "graphql" and payload["query"].startswith("query($owner"):
                reads += 1
                if reads == 2:
                    self.fake.issue["updatedAt"] = "2026-09-11T14:00:00Z"

        self.fake.hook = race
        with self.assertRaisesRegex(contract.ContractError, "changed during"):
            self.sync(repair_bot=REPAIR_BOT, write=True)
        self.assertEqual(self.fake.writes, [])

    def test_final_main_check_prevents_close_race(self):
        self.fake = FakeGitHub(success=True)
        self.fake.set_issue()
        reads = 0

        def advance(endpoint, payload):
            nonlocal reads
            if endpoint.endswith("/git/ref/heads/main"):
                reads += 1
                if reads == 3:
                    self.fake.ref = fixtures.branch_ref("b" * 40)

        self.fake.hook = advance
        with self.assertRaises(contract.MainAdvanced):
            self.sync(write=True)
        self.assertEqual(self.fake.writes, [])

    def test_journal_bound_duplicate_and_foreign_schema(self):
        for mutate in (lambda s: s.update(repository="other/repo"), lambda s: s.update(schema=True),
                       lambda s: s["runs"].append(s["runs"][0]), lambda s: s.update(status="perfect"),
                       lambda s: s.update(pull_requests=[True])):
            state = self.fake.state()
            mutate(state)
            with self.assertRaises(contract.ContractError):
                incident.parse(incident.render(state), REPO)


class BoundsAndCLITests(unittest.TestCase):
    def test_actual_isolated_cli_imports_trusted_siblings_outside_checkout(self):
        script = Path(incident.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            help_result = subprocess.run([sys.executable, "-I", "-B", str(script), "--help"],
                                         cwd=directory, capture_output=True, text=True, timeout=20)
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("{sync,watch}", help_result.stdout)
            rejected = subprocess.run([sys.executable, "-I", "-B", str(script), "watch", "--repository", "invalid"],
                                      cwd=directory, capture_output=True, text=True, timeout=20)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("Recovery incident not verified", rejected.stderr)
            self.assertNotIn("Traceback", rejected.stderr)

    def test_pagination_bound(self):
        class NeverEnds:
            def api(self, endpoint, **kwargs):
                page = int(parse_qs(urlsplit(endpoint).query)["page"][0])
                return [{"id": page * 100 + n} for n in range(100)]
        api = incident.BoundedAPI(NeverEnds())
        with self.assertRaisesRegex(contract.ContractError, "pagination"):
            api.inventory("repos/example/repo/issues")
        self.assertEqual(api.requests, incident.MAX_PAGES)

    def test_truncated_and_changing_count(self):
        transport = mock.Mock()
        transport.api.return_value = {"total_count": 2, "jobs": [{"id": 1}]}
        with self.assertRaisesRegex(contract.ContractError, "incomplete"):
            incident.BoundedAPI(transport).inventory("repos/example/repo/jobs", "jobs")
        transport.api.side_effect = [{"total_count": 101, "jobs": [{"id": n + 1} for n in range(100)]},
                                     {"total_count": 102, "jobs": [{"id": 101}]}]
        with self.assertRaisesRegex(contract.ContractError, "count changed"):
            incident.BoundedAPI(transport).inventory("repos/example/repo/jobs", "jobs")

    def test_request_and_time_bounds(self):
        api = incident.BoundedAPI(mock.Mock(), clock=lambda: 100)
        api.requests = incident.MAX_REQUESTS
        with self.assertRaises(contract.ContractError):
            api.api("anything")
        api = incident.BoundedAPI(mock.Mock(), clock=lambda: 100)
        api.deadline = 100
        with self.assertRaises(contract.ContractError):
            api.api("anything")

    def test_cli_real_controller_readonly_and_explicit_write(self):
        fake = FakeGitHub()
        args = ["sync", "--repository", REPO, "--run-id", str(RUN), "--run-attempt", "1", "--expected-sha", SHA]
        with mock.patch.object(incident, "GitHub", return_value=fake), mock.patch.dict("os.environ", {"SMOKE_NOTIFICATION_LOGIN": RECIPIENT}, clear=True), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(incident.main(args), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "needs_investigation")
            self.assertFalse(fake.writes)
            self.assertEqual(incident.main(args + ["--write"]), 0)
            self.assertEqual(len(fake.writes), 1)
            self.assertEqual(fake.writes[0][1]["assignees"], [RECIPIENT])

    def test_cli_recipient_overrides_environment(self):
        fake = FakeGitHub()
        args = ["sync", "--repository", REPO, "--run-id", str(RUN), "--run-attempt", "1", "--expected-sha", SHA,
                "--recipient", "explicit-owner", "--write"]
        with mock.patch.object(incident, "GitHub", return_value=fake), mock.patch.dict("os.environ", {"SMOKE_NOTIFICATION_LOGIN": RECIPIENT}, clear=True), mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(incident.main(args), 0)
            self.assertEqual(fake.writes[0][1]["assignees"], ["explicit-owner"])

    def test_cli_rejects_invalid_recipient_without_echoing_it(self):
        with mock.patch.dict("os.environ", {"SMOKE_NOTIFICATION_LOGIN": "private\n@injected"}, clear=True), mock.patch("sys.stderr", new_callable=io.StringIO) as errors:
            self.assertEqual(incident.main(["watch", "--repository", REPO, "--write"]), 1)
            self.assertNotIn("private", errors.getvalue())

    def test_cli_errors_do_not_leak(self):
        with mock.patch.object(incident, "sync", side_effect=contract.ContractError("secret internal log")), mock.patch("sys.stderr", new_callable=io.StringIO) as errors:
            self.assertEqual(incident.main(["sync", "--repository", REPO]), 1)
            self.assertNotIn("secret", errors.getvalue())

    def test_cli_watch_rejects_caller_selected_run(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(incident.main(["watch", "--repository", REPO, "--run-id", "123"]), 1)

    def test_watch_cli_runs_real_controller_and_respects_write_flag(self):
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 12, 5, tzinfo=timezone.utc)

        fake = FakeGitHub()
        fake.listed_parents = []
        with mock.patch.object(incident, "GitHub", return_value=fake), mock.patch.object(incident, "datetime", FrozenDatetime), mock.patch.dict("os.environ", {"SMOKE_NOTIFICATION_LOGIN": RECIPIENT}, clear=True), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(incident.main(["watch", "--repository", REPO]), 0)
            self.assertFalse(fake.writes)
            self.assertEqual(json.loads(output.getvalue())["reason"], "weekly_validation_missing")
            self.assertEqual(incident.main(["watch", "--repository", REPO, "--write"]), 0)
            self.assertEqual(len(fake.writes), 1)
            self.assertEqual(fake.writes[0][1]["assignees"], [RECIPIENT])


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGitHub()
        self.now = datetime(2026, 9, 11, 13, tzinfo=timezone.utc)

    def watch(self, **kwargs):
        kwargs.setdefault("recipient", RECIPIENT)
        return incident.watch(repository=REPO, repository_root=Path("."), api=self.fake, now=self.now, **kwargs)

    def test_completed_failure_is_persisted_by_watchdog(self):
        self.assertEqual(self.watch(write=True)["status"], "needs_investigation")
        self.assertEqual(self.fake.issue["state"], "OPEN")

    def test_missing_weekly_run_is_reported_and_idempotent(self):
        self.now = datetime(2026, 9, 12, 5, tzinfo=timezone.utc)
        self.fake.listed_parents = []
        result = self.watch(write=True)
        self.assertEqual(result["reason"], "weekly_validation_missing")
        self.assertTrue(result["written"])
        self.assertIn("weekly_validation_missing", self.fake.issue["body"])
        self.assertFalse(self.watch(write=True)["written"])
        self.assertEqual(len(self.fake.writes), 1)
        self.assertEqual(self.fake.writes[0][1]["assignees"], [RECIPIENT])

    def test_prior_week_success_does_not_hide_missing_run(self):
        self.now = datetime(2026, 9, 12, 5, tzinfo=timezone.utc)
        self.fake = FakeGitHub(success=True)
        self.fake.set_issue(self.fake.state("verified_green"))
        self.fake.issue["state"] = "CLOSED"
        result = self.watch(write=True)
        self.assertEqual(result["reason"], "weekly_validation_missing")
        self.assertEqual(self.fake.issue["state"], "OPEN")

    def test_grace_period_does_not_make_missing_run_green(self):
        self.now = datetime(2026, 9, 12, 3, 30, tzinfo=timezone.utc)
        self.fake.listed_parents = []
        result = self.watch(write=True)
        self.assertEqual(result["status"], "weekly_schedule_grace")
        self.assertFalse(self.fake.writes)

    def test_stuck_run_opens_incident_without_exposing_logs(self):
        self.fake.parent.update(status="in_progress", conclusion=None)
        self.now = datetime(2026, 9, 11, 22, tzinfo=timezone.utc)
        result = self.watch(write=True)
        self.assertEqual(result["reason"], "main_validation_stuck")
        self.assertEqual(self.fake.issue["state"], "OPEN")
        self.assertEqual(self.fake.writes[0][1]["assignees"], [RECIPIENT])

    def test_recent_active_run_stays_pending_not_green(self):
        self.fake.parent.update(status="queued", conclusion=None)
        self.fake.jobs[RUN] = []
        result = self.watch(write=True)
        self.assertEqual(result["status"], "validation_in_progress")
        self.assertFalse(self.fake.writes)

    def test_active_run_refreshes_existing_incident_waiting_status(self):
        self.fake.set_issue(self.fake.state("pending_manual_review"))
        self.fake.parent.update(status="in_progress", conclusion=None)
        result = self.watch(write=True)
        self.assertEqual(result["status"], "awaiting_full_main")
        self.assertEqual(result["reason"], "validation_in_progress")
        self.assertEqual(self.fake.issue["state"], "OPEN")

    def test_new_week_watchdog_starts_new_episode_after_verified_close(self):
        self.fake.set_issue(self.fake.state("verified_green"))
        self.fake.issue["state"] = "CLOSED"
        self.fake.listed_parents = []
        self.now = datetime(2026, 9, 12, 5, tzinfo=timezone.utc)
        self.watch(write=True)
        self.assertEqual(incident.parse(self.fake.issue["body"], REPO)["runs"], [])

    def test_site_only_scope_skip_does_not_satisfy_weekly_run(self):
        self.fake.parent.update(conclusion="success")
        self.fake.parent_job["conclusion"] = "skipped"
        result = self.watch(write=True)
        self.assertEqual(result["reason"], "weekly_validation_missing")
        self.assertEqual(self.fake.issue["state"], "OPEN")

    def test_completed_missing_orchestrator_job_is_investigation(self):
        self.fake.jobs[RUN] = [self.fake.scope_job]
        result = self.watch(write=True)
        self.assertEqual(result["reason"], "required_evidence_missing")
        self.assertEqual(result["status"], "needs_investigation")

    def test_untrusted_clock_and_run_window_rejected(self):
        self.now = self.now.replace(tzinfo=None)
        with self.assertRaises(contract.ContractError):
            self.watch()
        self.now = datetime(2026, 9, 23, 13, tzinfo=timezone.utc)
        with self.assertRaises(contract.ContractError):
            self.watch()

    def test_watchdog_does_not_overwrite_changed_run_inventory(self):
        self.fake.listed_parents = []
        reads = 0

        def race(endpoint, payload):
            nonlocal reads
            if "/workflows/test-all-packages-orchestrator.yml/runs" in endpoint:
                reads += 1
                if reads == 2:
                    self.fake.listed_parents = [self.fake.parent]

        self.fake.hook = race
        with self.assertRaisesRegex(contract.ContractError, "inventory changed"):
            self.watch(write=True)
        self.assertFalse(self.fake.writes)


if __name__ == "__main__":
    unittest.main()
