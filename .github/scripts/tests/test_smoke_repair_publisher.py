from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "smoke_repair_publisher.py"
SPEC = importlib.util.spec_from_file_location("tested_smoke_repair_publisher", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

BASE = "a" * 40
REPOSITORY = "example/dashboard"
WORKFLOW = ".github/workflows/test-example.yml"
BATCH = ".github/workflows/test-all-packages-batch1.yml"
POLICY_CONTRACT = {
    "expected_job_name": "test-example",
    "mandatory_step_names": [f"Test {i}" for i in range(1, 7)],
    "final_gate_step_name": "Calculate test summary",
}
SOURCE = """name: Test Example on Arm64
permissions:
  contents: read
on:
  workflow_dispatch:
  workflow_call:
jobs:
  test-example:
    runs-on: ubuntu-24.04-arm
    steps:
      - name: Checkout repository
        uses: actions/checkout@1111111111111111111111111111111111111111
        with:
          persist-credentials: false
      - name: Install package
        id: install
        run: |
          make -j4
"""
CANDIDATE = SOURCE.replace("make -j4", "make -j2")


class FakeGit:
    """In-memory Git fixture. No Git subprocesses, commits, or pushes occur."""

    def __init__(self, root, files):
        self.root = root
        self.base_entries = {path: ("100644", module._blob_id(text)) for path, text in files.items()}
        self.entries = copy.deepcopy(self.base_entries)
        self.commits = {BASE: {"entries": self.base_entries, "parents": [], "message": "Base"}}
        self.remote_main = BASE
        self.origin = f"https://github.com/{REPOSITORY}.git"
        self.branches = {}
        self.fetch_head = BASE
        self.calls = []
        self.blobs = {module._blob_id(text): text for text in files.values()}
        self.before = None
        self.extra_diff = []

    @staticmethod
    def tree(entries):
        return hashlib.sha1(json.dumps(entries, sort_keys=True).encode()).hexdigest()

    def text(self, *args):
        return self.run(*args).stdout.strip()

    def run(self, *args, input_text=None, check=True):
        self.calls.append(args)
        if self.before:
            self.before(args)
        output, status = "", 0
        if args[:2] == ("config", "--get"):
            output = self.origin
        elif args == ("rev-parse", "--show-toplevel"):
            output = str(self.root)
        elif args == ("rev-parse", "--verify", "HEAD^{commit}"):
            output = BASE
        elif args == ("rev-parse", "--verify", "FETCH_HEAD^{commit}"):
            output = self.fetch_head
        elif args[:2] == ("rev-parse", "--verify") and "refs/remotes/origin/main" in args[2]:
            output = self.remote_main
        elif args[0] == "rev-parse" and args[-1].endswith("^{tree}"):
            output = self.tree(self.commits[args[-1][:-7]]["entries"])
        elif args[:3] == ("diff", "--cached", "--quiet"):
            status = int(self.entries != self.base_entries)
        elif args[:2] == ("diff", "--cached"):
            output = "".join(path + "\0" for path in self.entries if self.entries[path] != self.base_entries.get(path))
        elif args[0] == "diff" and BASE in args:
            candidate = args[args.index(BASE) + 1]
            entries = self.commits[candidate]["entries"]
            paths = [path for path in set(entries) | set(self.base_entries) if entries.get(path) != self.base_entries.get(path)]
            output = "".join(path + "\0" for path in sorted(paths + self.extra_diff))
        elif args[0] == "diff":
            paths = [path for path, (_, blob) in self.base_entries.items()
                     if not (self.root / path).is_file() or module._blob_id((self.root / path).read_text()) != blob]
            output = "".join(path + "\0" for path in paths)
        elif args[:2] == ("ls-files", "--others"):
            output = ""
        elif args[:2] == ("ls-files", "--stage"):
            path = args[-1]
            mode, blob = self.entries[path]
            output = f"{mode} {blob} 0\t{path}\0"
        elif args[:2] == ("ls-tree", "-z"):
            commit, path = args[2], args[-1]
            entry = self.commits[commit]["entries"].get(path)
            if entry:
                output = f"{entry[0]} blob {entry[1]}\t{path}\0"
        elif args[0] == "ls-remote":
            branch = args[-1].removeprefix("refs/heads/")
            if branch in self.branches:
                output = f"{self.branches[branch]}\trefs/heads/{branch}\n"
        elif args[0] == "fetch":
            if args[-1].startswith("refs/heads/"):
                self.fetch_head = self.branches[args[-1].removeprefix("refs/heads/")]
        elif args[:2] == ("hash-object", "-w"):
            output = module._blob_id(input_text)
            self.blobs[output] = input_text
        elif args[:2] == ("update-index", "--cacheinfo"):
            mode, blob, path = args[2].split(",", 2)
            self.entries[path] = (mode, blob)
        elif args[0] == "write-tree":
            output = self.tree(self.entries)
        elif args[0] == "read-tree":
            self.entries = copy.deepcopy(self.base_entries)
        elif args[:3] == ("show", "-s", "--format=%P"):
            output = " ".join(self.commits[args[-1]]["parents"])
        elif args[:3] == ("show", "-s", "--format=%B"):
            output = self.commits[args[-1]]["message"]
        else:
            raise AssertionError(f"unexpected Git operation: {args}")
        return subprocess.CompletedProcess(args, status, output, "")


class FakeGitHub:
    def __init__(self, git):
        self.git = git
        self.calls = []
        self.prs = []
        self.trees = {}
        self.auth_calls = 0
        self.before = None
        self.runtime_mutation = None
        self.after_create = None

    def setup_git_auth(self):
        self.auth_calls += 1

    def _api(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, copy.deepcopy(payload)))
        if self.before:
            self.before(method, endpoint, payload)
        attempt = re.search(r"actions/runs/([0-9]+)/attempts/([0-9]+)$", endpoint)
        if method == "GET" and attempt:
            value = {
                "id": int(attempt[1]), "run_attempt": int(attempt[2]), "head_sha": BASE,
                "head_branch": "main", "path": ".github/workflows/test-all-packages-orchestrator.yml",
                "repository": {"full_name": REPOSITORY}, "head_repository": {"full_name": REPOSITORY},
            }
            if self.runtime_mutation:
                self.runtime_mutation(value)
            return value
        if method == "GET" and "/pulls?" in endpoint:
            return copy.deepcopy(self.prs)
        if method == "POST" and endpoint.endswith("/git/blobs"):
            source = base64.b64decode(payload["content"]).decode()
            blob = module._blob_id(source)
            self.git.blobs[blob] = source
            return {"sha": blob}
        if method == "POST" and endpoint.endswith("/git/trees"):
            entries = copy.deepcopy(self.git.base_entries)
            for entry in payload["tree"]:
                entries[entry["path"]] = (entry["mode"], entry["sha"])
            tree = self.git.tree(entries)
            self.trees[tree] = entries
            return {"sha": tree}
        if method == "POST" and endpoint.endswith("/git/commits"):
            sha = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            self.git.commits[sha] = {**copy.deepcopy(payload), "entries": self.trees[payload["tree"]]}
            return {"sha": sha, "tree": {"sha": payload["tree"]}, "message": payload["message"],
                    "parents": [{"sha": parent} for parent in payload["parents"]]}
        if method == "POST" and endpoint.endswith("/git/refs"):
            branch = payload["ref"].removeprefix("refs/heads/")
            if branch in self.git.branches:
                raise module.PublishError("ref already exists")
            self.git.branches[branch] = payload["sha"]
            return {"ref": payload["ref"], "object": {"sha": payload["sha"]}}
        raise AssertionError(f"unexpected GitHub call: {method} {endpoint}")

    def list_open_pull_requests(self, config):
        return copy.deepcopy([pr for pr in self.prs if pr["state"] == "open"])

    def create_pull_request(self, config, *, body, head_sha):
        pr = {
            "number": len(self.prs) + 1, "state": "open", "draft": True,
            "title": config.title, "body": body, "user": {"login": config.expected_pr_author_login},
            "head": {"ref": config.head_branch, "sha": head_sha, "repo": {"full_name": REPOSITORY}},
            "base": {"ref": "main", "sha": BASE, "repo": {"full_name": REPOSITORY}},
            "html_url": f"https://github.com/{REPOSITORY}/pull/{len(self.prs) + 1}",
        }
        self.prs.append(pr)
        if self.after_create:
            self.after_create(pr)
        return copy.deepcopy(pr)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout"
        self.root.mkdir()
        self.snapshot = {WORKFLOW: SOURCE.encode(), BATCH: b"batch fixture\n"}
        self.lock = {
            "schema_version": 3, "hardened_workflow_sha256": module.supply.workflow_snapshot_sha256(self.snapshot),
            "hardened_topology_sha256": "d" * 64, "updated_at": "unchanged",
            "actions": [{"original_ref": "actions/checkout@v4", "resolved_commit": "1" * 40, "occurrences": 1}],
            "containers": [], "permission_exceptions": [], "arbitrary_reviewed_metadata": {"retain": True},
        }
        self.files = {WORKFLOW: SOURCE, BATCH: "batch fixture\n", module.LOCK_PATH: json.dumps(self.lock, indent=2) + "\n"}
        for path, text in self.files.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git = FakeGit(self.root, self.files)
        self.github = FakeGitHub(self.git)
        self.context = {
            "repository": REPOSITORY, "base_sha": BASE, "orchestration_id": "orchestration-100-1",
            "orchestrator_run_id": 100, "orchestrator_run_attempt": 1, "package_slug": "example",
            "workflow_path": WORKFLOW, "called_job": "test-example", "source_text": SOURCE,
            "failed_steps": [{"name": "Install package"}], "log_excerpt": "bounded diagnostic",
            "batch": 1, "initial_run_id": 200, "confirmation_run_id": 201, "confirmation_job_id": 202,
        }
        self.proposal = {"diagnosis": "Bound build parallelism", "edits": [{"path": WORKFLOW, "old": "make -j4", "new": "make -j2"}], "unresolved_reason": ""}
        self.contract = {
            "called_job": "test-example", "job_name": "test-example", "mandatory_steps": POLICY_CONTRACT["mandatory_step_names"],
            "gate_step": POLICY_CONTRACT["final_gate_step_name"], "workflow_path": WORKFLOW,
            "source_digest": module._digest(CANDIDATE),
        }
        environment = {
            "GH_TOKEN": "fixture-only-not-a-credential", "SMOKE_REPAIR_APP_BOT_LOGIN": "repair[bot]",
            "SMOKE_REPAIR_APP_SLUG": "repair", "DASHBOARD_DELIVERY_APP_BOT_LOGIN": "generated[bot]",
            "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": BASE,
            "GITHUB_WORKFLOW_SHA": BASE, "GITHUB_RUN_ID": "100", "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/test-all-packages-orchestrator.yml@refs/heads/main",
        }
        self.start(patch.dict(os.environ, environment, clear=True))
        self.start(patch.object(module.publisher, "Git", return_value=self.git))
        self.start(patch.object(module.supply, "registered_workflows", return_value=[self.root / WORKFLOW]))
        self.start(patch.object(module.supply, "batch_paths", return_value=[self.root / BATCH]))
        self.start(patch.object(module.supply, "source_snapshot", side_effect=lambda *args: copy.deepcopy(self.snapshot)))
        self.start(patch.object(module.supply, "load_lock", side_effect=lambda *args: copy.deepcopy(self.lock)))
        self.start(patch("subprocess.run", side_effect=AssertionError("no real subprocesses in publisher tests")))
        self.start(patch("subprocess.Popen", side_effect=AssertionError("no real subprocesses in publisher tests")))
        self.policy = Mock(side_effect=self.admit)
        self.verifier = Mock(side_effect=lambda staged, receipt: receipt)

    def start(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    @staticmethod
    def admit(context, proposal):
        source = context["source_text"]
        for edit in proposal["edits"]:
            source = source.replace(edit["old"], edit["new"])
        return {
            "candidate_source": source, "contract": copy.deepcopy(POLICY_CONTRACT),
            "base_source_sha256": module._digest(context["source_text"]),
            "candidate_source_sha256": module._digest(source), "changed_step_ids": ["install"],
            "review_required": True, "semantic_equivalence_proven": False, "limitations": ["Review required"],
        }

    def stage(self, **kwargs):
        return module.stage(self.context, self.proposal, CANDIDATE, repository_root=self.root,
                            native_contract=self.contract, validate_apply=self.policy,
                            policy_version="1", github=self.github, **kwargs)

    def native(self, staged):
        return {
            "schema_version": 1, "stage": copy.deepcopy(staged), "status": "passed",
            "contract_digest": module._digest(module._json(self.contract)),
            "run": {
                "id": 300, "run_attempt": 1, "head_sha": staged["candidate_sha"], "head_branch": staged["branch"],
                "path": WORKFLOW, "event": "workflow_dispatch", "status": "completed", "conclusion": "success",
                "repository": REPOSITORY, "head_repository": REPOSITORY,
                "html_url": f"https://github.com/{REPOSITORY}/actions/runs/300",
            },
            "job": {"id": 301, "name": "test-example", "conclusion": "success", "html_url": f"https://github.com/{REPOSITORY}/actions/runs/300/job/301"},
            "steps": [{"name": "Test 1", "status": "completed", "conclusion": "success"}],
        }

    def open(self, staged, native=None, **kwargs):
        return module.open_pr(self.context, self.proposal, staged, native or self.native(staged),
                              repository_root=self.root, validate_apply=self.policy, policy_version="1",
                              verify_native=self.verifier, github=self.github, **kwargs)

    def test_admission_requires_no_environment_token_api_or_git_writes(self):
        with patch.dict(os.environ, {}, clear=True):
            artifact = module.build_candidate(self.context, self.proposal, repository_root=self.root, validate_apply=self.policy)
        self.assertEqual(artifact["candidate_source"], CANDIDATE)
        self.assertEqual(self.github.calls, [])
        self.assertFalse(any(call[0] in {"push", "commit", "commit-tree", "update-index", "fetch"} for call in self.git.calls))
        self.assertEqual((self.root / WORKFLOW).read_text(), SOURCE)

    def test_stage_has_frozen_schema_create_only_ref_and_no_pr(self):
        staged = self.stage()
        self.assertEqual(set(staged), module.STAGE_KEYS)
        self.assertEqual(staged["branch"], "automation/smoke-repair/100-1-example")
        self.assertEqual(staged["source_digest"], module._digest(CANDIDATE))
        self.assertEqual(self.github.prs, [])
        self.assertEqual(self.git.entries, self.git.base_entries)
        self.assertFalse(any(call[0] in {"push", "commit", "commit-tree", "checkout", "switch"} for call in self.git.calls))
        writes = [(method, endpoint) for method, endpoint, _ in self.github.calls if method != "GET"]
        self.assertEqual([endpoint.rsplit("/", 1)[1] for _, endpoint in writes], ["blobs", "blobs", "trees", "commits", "refs"])
        self.assertTrue(all(method == "POST" for method, _ in writes))
        audit = self.git.commits[staged["candidate_sha"]]["message"]
        self.assertIn('"workflow_ref":"example/dashboard/.github/workflows/test-all-packages-orchestrator.yml@refs/heads/main"', audit)
        self.assertNotIn("fixture-only-not-a-credential", audit)

    def test_reseal_changes_only_digest_and_transition(self):
        staged = self.stage()
        blob = self.git.commits[staged["candidate_sha"]]["entries"][module.LOCK_PATH][1]
        lock = json.loads(self.git.blobs[blob])
        original = copy.deepcopy(self.lock)
        transition = lock.pop("hardened_workflow_transition")
        new_digest = lock.pop("hardened_workflow_sha256")
        old_digest = original.pop("hardened_workflow_sha256")
        self.assertEqual(lock, original)
        expected_snapshot = {**self.snapshot, WORKFLOW: CANDIDATE.encode()}
        self.assertEqual(new_digest, module.supply.workflow_snapshot_sha256(expected_snapshot))
        self.assertEqual(transition["from_sha256"], old_digest)
        self.assertEqual(transition["to_sha256"], new_digest)
        self.assertEqual(transition["reason"], "Reseal bounded smoke repair 100-1-example; action references, pins, and topology unchanged.")

    def test_open_requires_live_verifier_and_returns_exact_draft(self):
        staged = self.stage()
        result = self.open(staged)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["head_sha"], staged["candidate_sha"])
        self.assertEqual(self.verifier.call_count, 3)
        self.assertTrue(self.github.prs[0]["draft"])
        self.assertIn("/actions/runs/200", self.github.prs[0]["body"])
        self.assertIn("/actions/runs/201/job/202", self.github.prs[0]["body"])
        self.assertIn("not full-fleet validation", self.github.prs[0]["body"])

    def test_exact_open_draft_replay_is_read_only(self):
        staged = self.stage()
        self.open(staged)
        writes = len([call for call in self.github.calls if call[0] != "GET"])
        self.assertEqual(self.open(staged)["status"], "unchanged")
        self.assertEqual(len(self.github.prs), 1)
        self.assertEqual(len([call for call in self.github.calls if call[0] != "GET"]), writes)

    def test_old_producer_attempt_can_be_opened_by_current_attempt_two(self):
        staged = self.stage()
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        result = self.open(staged)
        self.assertEqual(result["publisher"]["run_attempt"], 2)
        endpoints = [endpoint for method, endpoint, _ in self.github.calls if method == "GET"]
        self.assertIn(f"repos/{REPOSITORY}/actions/runs/100/attempts/1", endpoints)
        self.assertIn(f"repos/{REPOSITORY}/actions/runs/100/attempts/2", endpoints)
        self.assertNotIn(f"repos/{REPOSITORY}/actions/runs/100", endpoints)

    def test_preexisting_branch_always_refuses_stage_even_if_exact(self):
        self.stage()
        writes = len(self.github.calls)
        with self.assertRaisesRegex(module.PublishError, "already exists"):
            self.stage()
        self.assertTrue(all(method == "GET" for method, _, _ in self.github.calls[writes:]))

    def test_deleted_branch_with_closed_pr_history_cannot_be_recreated(self):
        staged = self.stage()
        self.open(staged)
        self.github.prs[0]["state"] = "closed"
        self.git.branches.clear()
        with self.assertRaisesRegex(module.PublishError, "already exists"):
            self.stage()

    def test_failed_native_validation_never_creates_a_pr(self):
        staged = self.stage()
        receipt = self.native(staged)
        receipt["status"] = "failed"
        with self.assertRaisesRegex(module.PublishError, "not passed"):
            self.open(staged, receipt)
        self.assertEqual(self.verifier.call_count, 0)
        self.assertEqual(self.github.prs, [])

    def test_forged_pass_is_rejected_by_live_callback(self):
        staged = self.stage()
        self.verifier.side_effect = module.PublishError("actual mandatory step failed")
        with self.assertRaisesRegex(module.PublishError, "mandatory step"):
            self.open(staged)
        self.assertEqual(self.github.prs, [])

    def test_success_is_rechecked_immediately_before_pr_creation(self):
        staged = self.stage()
        native = self.native(staged)
        self.verifier.side_effect = [native, module.PublishError("native run was rerun")]
        with self.assertRaisesRegex(module.PublishError, "rerun"):
            self.open(staged, native)
        self.assertEqual(self.github.prs, [])

    def test_main_advance_after_native_verification_blocks_pr(self):
        staged = self.stage()
        def advance(_, native):
            self.git.remote_main = "b" * 40
            return native
        self.verifier.side_effect = advance
        with self.assertRaisesRegex(module.PublishError, "base branch changed"):
            self.open(staged)
        self.assertEqual(self.github.prs, [])

    def test_branch_advance_after_native_verification_blocks_pr(self):
        staged = self.stage()
        def advance(_, native):
            self.git.branches[staged["branch"]] = "b" * 40
            return native
        self.verifier.side_effect = advance
        with self.assertRaisesRegex(module.PublishError, "branch no longer matches"):
            self.open(staged)
        self.assertEqual(self.github.prs, [])

    def test_native_callback_cannot_rewrite_receipt(self):
        staged = self.stage()
        self.verifier.side_effect = lambda _, receipt: {**receipt, "rewritten": True}
        with self.assertRaisesRegex(module.PublishError, "unchanged"):
            self.open(staged)

    def test_altered_receipt_fields_are_rejected(self):
        staged = self.stage()
        for key, value in (("base_sha", "c" * 40), ("source_digest", "0" * 64),
                           ("proposal_digest", "0" * 64), ("package_slug", "other"),
                           ("branch", "automation/smoke-repair/unowned"), ("schema_version", True)):
            with self.subTest(key=key):
                corrupted = {**staged, key: value}
                with self.assertRaises((ValueError, module.PublishError)):
                    self.open(corrupted)
        self.assertEqual(self.github.prs, [])

    def test_native_run_identity_and_urls_cannot_be_forged(self):
        staged = self.stage()
        for key, value in (("run_attempt", 2), ("run_attempt", True), ("head_sha", "c" * 40),
                           ("event", "pull_request"), ("repository", "other/repo"),
                           ("html_url", "https://example.com/claim"), ("id", True)):
            with self.subTest(key=key, value=value):
                receipt = self.native(staged)
                receipt["run"][key] = value
                with self.assertRaises(module.PublishError):
                    self.open(staged, receipt)
        self.assertEqual(self.github.prs, [])

    def test_candidate_wrong_parent_diff_lock_and_ownership_are_rejected(self):
        staged = self.stage()
        commit = self.git.commits[staged["candidate_sha"]]
        original = copy.deepcopy(commit)
        for mutation in (lambda: commit.update(parents=["f" * 40]),
                         lambda: commit.update(message="Unowned commit"),
                         lambda: self.git.extra_diff.append("README.md")):
            with self.subTest(mutation=mutation):
                commit.clear()
                commit.update(copy.deepcopy(original))
                self.git.extra_diff.clear()
                mutation()
                with self.assertRaises(module.PublishError):
                    self.open(staged)
        self.assertEqual(self.github.prs, [])

    def test_open_rejects_ready_closed_wrong_author_or_retargeted_pr(self):
        staged = self.stage()
        self.open(staged)
        original = copy.deepcopy(self.github.prs[0])
        for mutate in (lambda pr: pr.update(draft=False), lambda pr: pr.update(state="closed"),
                       lambda pr: pr["user"].update(login="generated[bot]"),
                       lambda pr: pr["base"].update(ref="other"), lambda pr: pr.update(body="human edited")):
            self.github.prs = [copy.deepcopy(original)]
            mutate(self.github.prs[0])
            with self.assertRaises(module.PublishError):
                self.open(staged)

    def test_missing_or_wrong_app_identity_fails_before_writes(self):
        for variable, value in (("GH_TOKEN", ""), ("SMOKE_REPAIR_APP_BOT_LOGIN", "generated[bot]"),
                                ("SMOKE_REPAIR_APP_SLUG", "generated"), ("DASHBOARD_DELIVERY_APP_BOT_LOGIN", ""),
                                ("SMOKE_REPAIR_APP_BOT_LOGIN", "github-actions[bot]")):
            with self.subTest(variable=variable, value=value), patch.dict(os.environ, {variable: value}):
                with self.assertRaises(module.PublishError):
                    self.stage()
        self.assertFalse(any(method != "GET" for method, _, _ in self.github.calls))

    def test_live_runtime_wrong_attempt_repository_workflow_or_sha_is_rejected(self):
        for field, value in (("run_attempt", 2), ("head_sha", "c" * 40), ("path", WORKFLOW),
                             ("repository", {"full_name": "other/repo"}), ("id", True)):
            with self.subTest(field=field):
                self.github.runtime_mutation = lambda run, field=field, value=value: run.update({field: value})
                with self.assertRaises(module.PublishError):
                    self.stage()
        self.assertFalse(any(method != "GET" for method, _, _ in self.github.calls))

    def test_old_producing_attempt_is_authenticated_independently(self):
        staged = self.stage()
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        def corrupt_old(run):
            if run["run_attempt"] == 1:
                run["head_sha"] = "c" * 40
        self.github.runtime_mutation = corrupt_old
        with self.assertRaisesRegex(module.PublishError, "runtime metadata"):
            self.open(staged)
        self.assertEqual(self.github.prs, [])

    def test_main_advance_during_object_upload_never_creates_ref(self):
        def advance(method, endpoint, payload):
            if method == "POST" and endpoint.endswith("/git/blobs"):
                self.git.remote_main = "b" * 40
        self.github.before = advance
        with self.assertRaises(module.PublishError):
            self.stage()
        self.assertFalse(self.git.branches)

    def test_ref_race_cannot_overwrite_existing_branch(self):
        def race(method, endpoint, payload):
            if method == "POST" and endpoint.endswith("/git/refs"):
                self.git.branches[payload["ref"].removeprefix("refs/heads/")] = "f" * 40
        self.github.before = race
        with self.assertRaisesRegex(module.PublishError, "ref already exists"):
            self.stage()
        self.assertEqual(list(self.git.branches.values()), ["f" * 40])

    def test_model_cannot_edit_action_lock(self):
        self.proposal["edits"][0]["path"] = module.LOCK_PATH
        with self.assertRaisesRegex(module.PublishError, "only the selected"):
            self.stage()
        self.assertEqual(self.policy.call_count, 0)

    def test_reseal_rejects_action_pin_and_topology_changes_even_if_policy_admits(self):
        for source in (CANDIDATE.replace("1" * 40, "2" * 40),
                       CANDIDATE.replace("ubuntu-24.04-arm", "ubuntu-latest"),
                       CANDIDATE.replace("  test-example:", "  other-job:")):
            with self.subTest(source=source):
                with self.assertRaises(module.PublishError):
                    module.reseal_workflow_lock(self.root, base_sha=BASE, workflow_path=WORKFLOW, source=source, repair_id="100-1-example")

    def test_mismatched_native_contract_is_rejected_before_writes(self):
        for field, value in (("source_digest", "0" * 64), ("mandatory_steps", []), ("gate_step", "Other")):
            original = self.contract[field]
            self.contract[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(module.PublishError, "contracts disagree"):
                self.stage()
            self.contract[field] = original
        self.assertFalse(any(method != "GET" for method, _, _ in self.github.calls))

    def test_slug_and_registered_filename_are_independent(self):
        self.context["package_slug"] = "canonical_alias"
        staged = self.stage()
        self.assertEqual(staged["workflow_path"], WORKFLOW)
        self.assertEqual(staged["repair_id"], "100-1-canonical_alias")

    def test_proposal_and_context_are_not_mutated(self):
        before = copy.deepcopy((self.context, self.proposal))
        staged = self.stage()
        self.open(staged)
        self.assertEqual((self.context, self.proposal), before)

    def test_cli_admit_is_token_free_and_creates_private_external_artifact(self):
        parent = self.root.parent
        context, proposal, output = parent / "context.json", parent / "proposal.json", parent / "candidate.json"
        context.write_text(json.dumps(self.context))
        proposal.write_text(json.dumps(self.proposal))
        policy = Mock(POLICY_VERSION="1", validate_proposal=self.policy)
        with patch.dict(os.environ, {}, clear=True), patch.object(module, "_module", return_value=policy):
            status = module.main(["admit", "--context", str(context), "--proposal", str(proposal),
                                  "--repository-root", str(self.root), "--output", str(output)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.read_text())["candidate_source"], CANDIDATE)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.github.calls, [])

    def test_cli_rejects_output_inside_checkout_before_any_remote_call(self):
        status = module.main(["stage", "--context", "unused", "--proposal", "unused",
                              "--candidate", "unused", "--native-contract", "unused",
                              "--repository-root", str(self.root), "--output", str(self.root / "receipt.json")])
        self.assertEqual(status, 1)
        self.assertEqual(self.github.calls, [])

    def test_actual_policy_and_native_helpers_agree_with_stage_interchange(self):
        fixture = module._module("publisher_policy_fixture", SCRIPT.parent / "tests/test_smoke_repair_policy.py")
        policy = module._module("publisher_actual_policy", SCRIPT.parent / "smoke_repair_policy.py")
        native = module._module("publisher_actual_native", SCRIPT.parent / "smoke_repair_native.py")
        source = fixture.SOURCE.replace("Widget", "Example").replace("widget", "example")
        self.context["source_text"] = source
        self.proposal["edits"] = [{"path": WORKFLOW, "old": "sudo apt-get install -y build-essential",
                                   "new": "sudo apt-get install -y build-essential libfuse3-dev"}]
        self.snapshot[WORKFLOW] = source.encode()
        self.lock["hardened_workflow_sha256"] = module.supply.workflow_snapshot_sha256(self.snapshot)
        self.files[WORKFLOW] = source
        self.files[module.LOCK_PATH] = json.dumps(self.lock, indent=2) + "\n"
        for path, text in self.files.items():
            (self.root / path).write_text(text)
        self.git.__init__(self.root, self.files)
        admitted = module.build_candidate(self.context, self.proposal, repository_root=self.root,
                                           validate_apply=policy.validate_proposal)
        source = admitted["candidate_source"]
        contract = native.derive_native_contract(
            self.context["source_text"].encode(), repository=REPOSITORY, base_sha=BASE,
            workflow_path=WORKFLOW, package_slug=self.context["package_slug"],
            called_job=self.context["called_job"], source_digest=module._digest(source),
        )
        staged = module.stage(self.context, self.proposal, source, repository_root=self.root,
                              native_contract=contract, validate_apply=policy.validate_proposal,
                              policy_version="1", github=self.github)
        self.assertEqual(native.validate_stage(staged), staged)
        audit = module.decode_json(self.git.commits[staged["candidate_sha"]]["message"].split("Smoke-Repair-Receipt: ", 1)[1])
        self.assertEqual(audit["native_contract_digest"], native._digest(contract))

    def test_cli_stage_and_open_use_stable_policy_and_native_signatures(self):
        parent = self.root.parent
        paths = {name: parent / f"{name}.json" for name in ("context", "proposal", "candidate", "contract", "stage", "native", "result")}
        artifact = module.build_candidate(self.context, self.proposal, repository_root=self.root, validate_apply=self.policy)
        for key, value in (("context", self.context), ("proposal", self.proposal), ("candidate", artifact), ("contract", self.contract)):
            paths[key].write_text(json.dumps(value))
        common = ["--context", str(paths["context"]), "--proposal", str(paths["proposal"]),
                  "--repository-root", str(self.root), "--native-contract", str(paths["contract"])]
        policy = Mock(POLICY_VERSION="1", validate_proposal=self.policy)
        native = Mock()
        native.verify_native_receipt.side_effect = lambda staged, receipt, contract, **kwargs: self.verifier(staged, receipt)
        def implementation(name, path):
            return native if path.name == "smoke_repair_native.py" else policy
        summary = parent / "summary.md"
        step_output = parent / "step-output"
        summary.write_text("Existing summary\n")
        step_output.write_text("existing=output\n")
        with patch.object(module, "_module", side_effect=implementation), patch.object(module.publisher, "GhClient", return_value=self.github), patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(step_output)}):
            self.assertEqual(module.main(["stage", *common, "--candidate", str(paths["candidate"]), "--output", str(paths["stage"])]), 0)
            self.assertEqual(summary.read_text(), "Existing summary\n")
            self.assertEqual(step_output.read_text(), "existing=output\n")
            staged = json.loads(paths["stage"].read_text())
            paths["native"].write_text(json.dumps(self.native(staged)))
            self.assertEqual(module.main(["open-pr", *common, "--stage", str(paths["stage"]),
                                          "--native-receipt", str(paths["native"]), "--output", str(paths["result"])]), 0)
            self.assertEqual(module.main(["open-pr", *common, "--stage", str(paths["stage"]),
                                          "--native-receipt", str(paths["native"]), "--output", str(parent / "recovered.json")]), 0)
        self.assertEqual(json.loads(paths["result"].read_text())["status"], "created")
        self.assertEqual(json.loads((parent / "recovered.json").read_text())["status"], "unchanged")
        self.assertEqual(native.verify_native_receipt.call_args.args[2], self.contract)
        deadlines = [call.kwargs["deadline"] for call in native.verify_native_receipt.call_args_list]
        self.assertTrue(all(isinstance(deadline, float) for deadline in deadlines))
        self.assertEqual(deadlines[:3], [deadlines[0]] * 3)
        url = json.loads(paths["result"].read_text())["pr_url"]
        expected = f"\n[Smoke repair draft PR]({url})\n\nHuman review and required PR checks remain pending.\n"
        self.assertEqual(summary.read_text(), "Existing summary\n" + expected * 2)
        self.assertEqual(step_output.read_text(), "existing=output\n" + f"pull_request_url={url}\n" * 2)

    def test_workflow_outputs_reject_untrusted_urls_and_non_success_results(self):
        summary = self.root.parent / "summary.md"
        output = self.root.parent / "step-output"
        valid = {"status": "created", "pr_url": f"https://github.com/{REPOSITORY}/pull/7"}
        with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(output)}):
            for mutation in ({"status": "failed"}, {"pr_url": "https://example.com/pull/7"},
                             {"pr_url": valid["pr_url"] + "\nsecret"},
                             {"pr_url": "https://github.com/another/repo/pull/7"}):
                with self.subTest(mutation=mutation), self.assertRaises(module.PublishError):
                    module._write_publication_outputs({**valid, **mutation}, REPOSITORY)
        self.assertFalse(summary.exists())
        self.assertFalse(output.exists())

    def test_step_output_does_not_require_a_summary_environment(self):
        output = self.root.parent / "step-output"
        url = f"https://github.com/{REPOSITORY}/pull/7"
        with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}, clear=True):
            module._write_publication_outputs({"status": "created", "pr_url": url}, REPOSITORY)
        self.assertEqual(output.read_text(), f"pull_request_url={url}\n")

    def test_cli_errors_do_not_leak_dependency_content_or_claim_success(self):
        parent = self.root.parent
        summary, output = parent / "summary.md", parent / "result.json"
        step_output = parent / "step-output"
        arguments = ["open-pr", "--context", "context", "--proposal", "proposal",
                     "--stage", "stage", "--native-receipt", "native", "--native-contract", "contract",
                     "--repository-root", str(self.root), "--output", str(output)]
        secret = "remote proposal content " + os.environ["GH_TOKEN"]
        for error in (module.PublishError(secret), ValueError(secret), KeyError(secret),
                      RuntimeError(secret), subprocess.CalledProcessError(1, secret, stderr=secret)):
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(error=type(error).__name__), patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(step_output)}), patch.object(module, "_module", return_value=Mock(POLICY_VERSION="1")), patch.object(module, "_load", side_effect=[self.context, self.proposal, self.contract, {}, {}]), patch.object(module, "open_pr", side_effect=error), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                self.assertEqual(module.main(arguments), 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "smoke repair publication failed closed; no successful repair is claimed.\n")
            self.assertFalse(summary.exists())
            self.assertFalse(output.exists())
            self.assertFalse(step_output.exists())

    def test_replayed_context_with_different_failure_provenance_is_rejected(self):
        staged = self.stage()
        self.context["confirmation_run_id"] = 999
        with self.assertRaisesRegex(module.PublishError, "stage audit"):
            self.open(staged)
        self.assertEqual(self.github.prs, [])

    def test_reseal_rejects_wrong_base_digest(self):
        self.lock["hardened_workflow_sha256"] = "0" * 64
        text = json.dumps(self.lock, indent=2) + "\n"
        (self.root / module.LOCK_PATH).write_text(text)
        self.git.base_entries[module.LOCK_PATH] = ("100644", module._blob_id(text))
        self.git.entries = copy.deepcopy(self.git.base_entries)
        with self.assertRaisesRegex(module.PublishError, "base workflow digest"):
            self.stage()
        self.assertFalse(any(method != "GET" for method, _, _ in self.github.calls))

    def test_dirty_or_symlink_source_never_reaches_publication(self):
        target = self.root / WORKFLOW
        target.write_text(SOURCE + "# dirty\n")
        with self.assertRaisesRegex(module.PublishError, "clean worktree"):
            self.stage()
        target.unlink()
        other = self.root.parent / "source.yml"
        other.write_text(SOURCE)
        target.symlink_to(other)
        with self.assertRaisesRegex(module.PublishError, "symlinks"):
            self.stage()
        self.assertFalse(any(method != "GET" for method, _, _ in self.github.calls))

    def test_failed_postpublication_guard_does_not_claim_success_or_merge(self):
        staged = self.stage()
        self.github.after_create = lambda pr: setattr(self.git, "remote_main", "b" * 40)
        with self.assertRaisesRegex(module.PublishError, "base branch changed"):
            self.open(staged)
        self.assertEqual(len(self.github.prs), 1)
        self.assertTrue(self.github.prs[0]["draft"])

    def test_stage_rechecks_admitted_source_after_policy(self):
        with self.assertRaisesRegex(module.PublishError, "reapplied policy"):
            module.stage(self.context, self.proposal, CANDIDATE + "# injected\n", repository_root=self.root,
                         native_contract=self.contract, validate_apply=self.policy, policy_version="1", github=self.github)
        self.assertFalse(any(method != "GET" for method, _, _ in self.github.calls))


if __name__ == "__main__":
    unittest.main()
