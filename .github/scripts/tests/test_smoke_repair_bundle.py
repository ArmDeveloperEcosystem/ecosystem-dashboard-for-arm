"""Bundle trust-boundary tests using existing in-memory Git/GitHub fixtures."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parent))
import smoke_repair_bundle as bundle


def load_fixture(name, filename):
    spec = importlib.util.spec_from_file_location(name, DIRECTORY / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixtures = load_fixture("bundle_publisher_fixtures", "test_smoke_repair_publisher.py")
fixtures.REPOSITORY = "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm"
policy_fixtures = load_fixture("bundle_policy_fixtures", "test_smoke_repair_policy.py")
single = fixtures.module


class BundleTests(unittest.TestCase):
    start = fixtures.PublisherTests.start
    admit = staticmethod(fixtures.PublisherTests.admit)
    catalog = fixtures.PublisherTests.catalog
    bind_catalog = fixtures.PublisherTests.bind_catalog

    def setUp(self):
        fixtures.PublisherTests.setUp(self)
        self.start(patch.object(bundle, "single", single))
        self.start(patch.object(bundle, "publisher", single.publisher))
        self.start(patch.object(bundle, "PublishError", single.PublishError))
        os.environ["GITHUB_WORKFLOW_REF"] = f"{fixtures.REPOSITORY}/.github/workflows/smoke-repair-cycle.yml@refs/heads/main"
        os.environ["GITHUB_EVENT_NAME"] = "repository_dispatch"
        self.github.runtime_mutation = lambda run: run.update(path=".github/workflows/smoke-repair-cycle.yml")
        other = copy.deepcopy(self.context)
        other.update(package_slug="zeta", workflow_path=".github/workflows/test-zeta.yml",
                     source_text=fixtures.SOURCE.replace("example", "zeta"), called_job="test-zeta",
                     confirmation_job_id=203)
        proposal = copy.deepcopy(self.proposal)
        proposal["edits"][0]["path"] = other["workflow_path"]
        self.request = {
            "schema_version": 1, "repository": fixtures.REPOSITORY, "base_sha": fixtures.BASE,
            "cycle_id": "100-1", "iteration": 1,
            "packages": [{"context": self.context, "proposal": self.proposal},
                         {"context": other, "proposal": proposal}],
        }
        self._install_workflows()
        self.current = Mock(side_effect=lambda request: request)
        self.fleet_verifier = Mock(side_effect=lambda descriptor, receipt: receipt)

    def _install_workflows(self):
        paths = []
        records = []
        pairs = []
        for item in self.request["packages"]:
            context = item["context"]
            path, text = context["workflow_path"], context["source_text"]
            (self.root / path).write_text(text)
            self.git.base_entries[path] = ("100644", single._blob_id(text))
            self.git.blobs[single._blob_id(text)] = text
            self.snapshot[path] = text.encode()
            paths.append(self.root / path)
            record = copy.deepcopy(self.catalog()["records"][0])
            record["slug"] = context["package_slug"]
            record["content_path"] = f"content/linux/opensource_packages/{context['package_slug']}.md"
            record["workflow"] = {"path": path, "presence": "present", "sha256": single._digest(text)}
            for dimension in record["registries"].values():
                dimension["evidence"][0].update(source_locator=path, evidence_sha256=single._digest(text))
            records.append(record)
            pairs.extend(((record["content_path"], record["content_sha256"]), (path, single._digest(text))))
        self.lock["hardened_workflow_sha256"] = single.supply.workflow_snapshot_sha256(self.snapshot)
        raw_lock = json.dumps(self.lock, indent=2) + "\n"
        (self.root / single.LOCK_PATH).write_text(raw_lock)
        self.git.base_entries[single.LOCK_PATH] = ("100644", single._blob_id(raw_lock))
        self.git.blobs[single._blob_id(raw_lock)] = raw_lock
        catalog = self.catalog()
        catalog["records"] = records
        catalog["corpus"].update(entry_count=len(records), corpus_sha256=single.bindings.catalog_validator.calculate_corpus_sha256(pairs))
        self.bind_catalog(catalog)
        self.start(patch.object(single.supply, "registered_workflows", return_value=paths))

    def readmit(self, request=None):
        return bundle.readmit(request or self.request, repository_root=self.root, validate_apply=self.policy)

    def stage(self, request=None, admitted=None):
        request = request or self.request
        return bundle.stage(request, admitted or self.readmit(request), repository_root=self.root,
                            validate_apply=self.policy, verify_current=self.current, github=self.github)

    def verify(self, staged, request=None):
        return bundle.verify(request or self.request, staged, repository_root=self.root,
                             validate_apply=self.policy, verify_current=self.current, github=self.github)

    @staticmethod
    def receipt(staged):
        return {"schema_version": 1, "descriptor": copy.deepcopy(staged["candidate"]), "status": "success",
                "kind": "smoke-repair-candidate-fleet", "publishing": False,
                "fleet_evidence": {"fixture": "live verifier independently authenticates this data"}}

    def open(self, staged, receipt=None, **kwargs):
        return bundle.open_draft(self.request, staged, receipt or self.receipt(staged), repository_root=self.root,
                                 validate_apply=self.policy, verify_current=self.current,
                                 verify_fleet=self.fleet_verifier, github=self.github, **kwargs)

    def assert_no_writes(self):
        self.assertEqual([], [call for call in self.github.calls if call[0] != "GET"])
        self.assertEqual([], self.github.prs)

    def test_readmission_is_offline_and_preserves_original_policy_per_package(self):
        with patch.dict(os.environ, {}, clear=True):
            plan = self.readmit()
        self.assertEqual(2, self.policy.call_count)
        self.assertEqual(self.request["packages"][0]["context"], self.policy.call_args_list[0].args[0])
        self.assertEqual(2, len(plan["packages"]))
        self.assertEqual([], self.github.calls)
        self.assertFalse(any(call[0] in {"push", "commit", "commit-tree", "update-index", "fetch"}
                             for call in self.git.calls))
        self.assertEqual(self.git.entries, self.git.base_entries)

    def test_cumulative_lock_preserves_all_other_metadata_and_all_workflow_changes(self):
        plan = self.readmit()
        lock = json.loads(plan["candidate_lock"])
        snapshot = copy.deepcopy(self.snapshot)
        for package in plan["packages"]:
            snapshot[package["workflow_path"]] = package["candidate_source"].encode()
        self.assertEqual(single.supply.workflow_snapshot_sha256(snapshot), lock["hardened_workflow_sha256"])
        for key, value in self.lock.items():
            if key != "hardened_workflow_sha256":
                self.assertEqual(value, lock[key])
        self.assertEqual(self.lock["hardened_workflow_sha256"], lock["hardened_workflow_transition"]["from_sha256"])

    def test_two_commits_bind_all_sources_and_one_catalog_anchor(self):
        staged = self.stage()
        descriptor, audit = staged["candidate"], staged["attestation"]
        self.assertEqual(bundle.DESCRIPTOR_KEYS, set(descriptor))
        self.assertEqual("automation/smoke-repair-cycle/100-1/iteration-1", descriptor["branch"])
        self.assertEqual(3, len(self.git.commits))
        anchor = self.git.commits[audit["source_anchor"]["sha"]]
        final = self.git.commits[descriptor["candidate_sha"]]
        workflows = {item["context"]["workflow_path"] for item in self.request["packages"]}
        changed = lambda commit: {path for path, entry in commit["entries"].items()
                                  if self.git.base_entries.get(path) != entry}
        self.assertEqual(workflows, changed(anchor))
        self.assertEqual(workflows | {single.CATALOG_PATH, single.LOCK_PATH}, changed(final))
        self.assertEqual([fixtures.BASE], anchor["parents"])
        self.assertEqual([audit["source_anchor"]["sha"]], final["parents"])
        catalog = json.loads(self.git.blobs[final["entries"][single.CATALOG_PATH][1]])
        for record in catalog["records"]:
            source = self.git.blobs[final["entries"][record["workflow"]["path"]][1]]
            self.assertEqual(single._digest(source), record["workflow"]["sha256"])
            for registry in record["registries"].values():
                evidence = registry["evidence"][0]
                self.assertEqual(audit["source_anchor"]["sha"], evidence["source_revision"])
                self.assertEqual("repair[bot]", evidence["verified_by"])
                self.assertEqual(audit["source_anchor"]["verified_at"], evidence["verified_at"])
        self.assertEqual(staged, self.verify(staged))
        self.assertEqual([], self.github.prs)
        self.assertEqual(self.git.entries, self.git.base_entries)

    def test_duplicate_stage_never_updates_an_existing_branch(self):
        staged = self.stage()
        writes = len([call for call in self.github.calls if call[0] != "GET"])
        with self.assertRaisesRegex(single.PublishError, "refusing replay"):
            self.stage()
        self.assertEqual(writes, len([call for call in self.github.calls if call[0] != "GET"]))
        self.assertEqual(staged["candidate"]["candidate_sha"], self.git.branches[staged["candidate"]["branch"]])

    def test_each_iteration_is_a_new_branch_against_the_original_base(self):
        first = self.stage()
        request = copy.deepcopy(self.request)
        request["iteration"] = 2
        request["packages"][1]["proposal"]["edits"][0]["new"] = "make -j1"
        second = self.stage(request)
        self.assertNotEqual(first["candidate"]["candidate_sha"], second["candidate"]["candidate_sha"])
        self.assertEqual(2, len(self.git.branches))
        self.assertEqual(fixtures.BASE, second["candidate"]["base_sha"])
        self.assertEqual([fixtures.BASE], self.git.commits[second["attestation"]["source_anchor"]["sha"]]["parents"])
        with self.assertRaisesRegex(single.PublishError, "cycle or iteration"):
            self.verify(first, request)

    def test_duplicate_case_colliding_unsorted_and_unrelated_packages_are_rejected(self):
        variants = []
        duplicate = copy.deepcopy(self.request)
        duplicate["packages"].append(copy.deepcopy(duplicate["packages"][0]))
        variants.append(duplicate)
        case = copy.deepcopy(self.request)
        case["packages"][1]["context"].update(package_slug="Example", workflow_path=".github/workflows/test-Example.yml")
        case["packages"][1]["proposal"]["edits"][0]["path"] = ".github/workflows/test-Example.yml"
        variants.append(case)
        unsorted = copy.deepcopy(self.request)
        unsorted["packages"].reverse()
        variants.append(unsorted)
        unrelated = copy.deepcopy(self.request)
        unrelated["packages"][1]["proposal"]["edits"][0]["path"] = "README.md"
        variants.append(unrelated)
        for request in variants:
            with self.subTest(request=request), self.assertRaises((ValueError, single.PublishError)):
                self.readmit(request)
        self.assert_no_writes()

    def test_request_rejects_model_authority_metadata_and_invalid_bounds(self):
        for field, value in (("candidate_sha", "c" * 40), ("publisher", {}), ("iteration", True),
                             ("iteration", 0), ("iteration", 4), ("cycle_id", "orchestration-100-1"),
                             ("schema_version", True), ("base_sha", "x" * 40), ("packages", [])):
            request = {**copy.deepcopy(self.request), field: value}
            with self.subTest(field=field, value=value), self.assertRaises((ValueError, single.PublishError)):
                self.readmit(request)
        self.assert_no_writes()

    def test_mixed_base_repository_or_cycle_is_rejected(self):
        for field, value in (("base_sha", "b" * 40), ("repository", "other/dashboard"),
                             ("orchestration_id", "orchestration-101-1")):
            request = copy.deepcopy(self.request)
            request["packages"][1]["context"][field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, single.PublishError)):
                self.readmit(request)
        self.assert_no_writes()

    def test_one_rejected_package_rejects_entire_bundle_before_writes(self):
        def reject(context, proposal):
            if context["package_slug"] == "zeta":
                raise single.PublishError("policy rejected")
            return self.admit(context, proposal)
        self.policy.side_effect = reject
        with self.assertRaisesRegex(single.PublishError, "policy rejected"):
            self.stage()
        self.assert_no_writes()

    def test_preflight_source_or_lock_metadata_spoof_is_rejected(self):
        for field in ("candidate_source", "source_digest", "context_digest", "policy_result_digest"):
            admitted = self.readmit()
            admitted["packages"][0][field] = "spoofed"
            with self.subTest(field=field), self.assertRaisesRegex(single.PublishError, "independent readmission"):
                self.stage(admitted=admitted)
        admitted = self.readmit()
        admitted["candidate_lock"] = "{}"
        with self.assertRaisesRegex(single.PublishError, "independent readmission"):
            self.stage(admitted=admitted)
        self.assert_no_writes()

    def test_current_verifier_required_and_must_return_authenticated_request(self):
        for verifier in (None, lambda request: None, lambda request: {**request, "iteration": 2}):
            self.current = verifier
            with self.subTest(verifier=verifier), self.assertRaises(single.PublishError):
                self.stage()
        self.assert_no_writes()

    def test_stale_base_or_active_iteration_prevents_any_publish(self):
        self.git.remote_main = "b" * 40
        with self.assertRaises(single.PublishError):
            self.stage()
        self.assert_no_writes()
        self.git.remote_main = fixtures.BASE
        self.current.side_effect = single.PublishError("cycle superseded")
        with self.assertRaisesRegex(single.PublishError, "cycle superseded"):
            self.stage()
        self.assert_no_writes()

    def test_legacy_workflow_and_mismatched_app_are_rejected(self):
        for key, value in (("GITHUB_WORKFLOW_REF", f"{fixtures.REPOSITORY}/.github/workflows/smoke-repair-receive.yml@refs/heads/main"),
                           ("SMOKE_REPAIR_APP_BOT_LOGIN", "generated[bot]"),
                           ("GITHUB_WORKFLOW_SHA", "f" * 40)):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaises(single.PublishError):
                self.stage()
        self.assert_no_writes()

    def test_cannot_open_without_exact_live_full_fleet_success(self):
        staged = self.stage()
        for key, value in (("status", "failed"), ("schema_version", True), ("descriptor", {})):
            receipt = {**self.receipt(staged), key: value}
            with self.subTest(key=key), self.assertRaisesRegex(single.PublishError, "fleet receipt"):
                self.open(staged, receipt)
        self.fleet_verifier.side_effect = single.PublishError("live batch failed")
        with self.assertRaisesRegex(single.PublishError, "live batch failed"):
            self.open(staged)
        self.assertEqual([], self.github.prs)

    def test_package_only_or_another_iterations_fleet_receipt_never_creates_pr(self):
        staged = self.stage()
        receipts = [{"schema_version": 1, "stage": staged, "status": "passed", "run": {"id": 300}},
                    self.receipt(staged), self.receipt(staged)]
        receipts[1]["descriptor"]["iteration"] = 2
        receipts[2]["descriptor"]["candidate_sha"] = staged["attestation"]["source_anchor"]["sha"]
        for receipt in receipts:
            with self.subTest(receipt=receipt), self.assertRaises(single.PublishError):
                self.open(staged, receipt)
        self.assertEqual([], self.github.prs)
        self.fleet_verifier.assert_not_called()

    def test_fleet_verifier_cannot_normalize_or_replace_receipt(self):
        staged = self.stage()
        self.fleet_verifier.side_effect = lambda descriptor, receipt: {**receipt, "extra": "not authenticated"}
        with self.assertRaisesRegex(single.PublishError, "unchanged live-verified"):
            self.open(staged)
        self.assertEqual([], self.github.prs)

    def test_open_exact_draft_is_idempotent_and_does_not_publish_model_prose(self):
        self.request["packages"][0]["proposal"]["diagnosis"] = "MODEL_PRIVATE_MARKER https://private.invalid/log"
        staged = self.stage()
        result = self.open(staged)
        self.assertEqual("created", result["status"])
        self.assertEqual("unchanged", self.open(staged)["status"])
        self.assertEqual(1, len(self.github.prs))
        self.assertTrue(self.github.prs[0]["draft"])
        self.assertIsNone(self.github.prs[0]["auto_merge"])
        self.assertNotIn("MODEL_PRIVATE_MARKER", self.github.prs[0]["body"])
        self.assertNotIn("private.invalid", self.github.prs[0]["body"])
        self.assertGreaterEqual(self.fleet_verifier.call_count, 5)
        self.assertFalse(any(call[0] in {"PATCH", "DELETE", "PUT"} for call in self.github.calls))
        self.assertFalse(any(call[0] == "push" for call in self.git.calls))

    def test_branch_or_main_advance_during_live_verification_prevents_draft(self):
        staged = self.stage()
        def advance(descriptor, receipt):
            self.git.branches[descriptor["branch"]] = "e" * 40
            return receipt
        self.fleet_verifier.side_effect = advance
        with self.assertRaisesRegex(single.PublishError, "immutable candidate"):
            self.open(staged)
        self.assertEqual([], self.github.prs)
        self.git.branches[staged["candidate"]["branch"]] = staged["candidate"]["candidate_sha"]
        def advance_main(descriptor, receipt):
            self.git.remote_main = "e" * 40
            return receipt
        self.fleet_verifier.side_effect = advance_main
        with self.assertRaises(single.PublishError):
            self.open(staged)
        self.assertEqual([], self.github.prs)

    def test_catalog_anchor_source_mode_or_unrelated_diff_tampering_prevents_pr(self):
        staged = self.stage()
        sha = staged["candidate"]["candidate_sha"]
        original = copy.deepcopy(self.git.commits[sha])
        for path in (single.CATALOG_PATH, single.LOCK_PATH, fixtures.WORKFLOW):
            self.git.commits[sha] = copy.deepcopy(original)
            self.git.commits[sha]["entries"][path] = ("120000", "f" * 40)
            with self.subTest(path=path), self.assertRaises(single.PublishError):
                self.open(staged)
        self.git.commits[sha] = original
        self.git.extra_diff = ["README.md"]
        with self.assertRaisesRegex(single.PublishError, "path allowlist"):
            self.open(staged)
        self.assertEqual([], self.github.prs)

    def test_attestation_or_descriptor_metadata_cannot_be_spoofed(self):
        original = self.stage()
        for field, value in (("plan_digest", "a" * 64), ("request_digest", "b" * 64),
                             ("policy_version", "2"), ("package_digests", []), ("source_anchor", None)):
            staged = copy.deepcopy(original)
            staged["attestation"][field] = value
            with self.subTest(field=field), self.assertRaises(single.PublishError):
                self.open(staged)
        staged = copy.deepcopy(original)
        staged["candidate"]["iteration"] = 2
        with self.assertRaises(single.PublishError):
            self.open(staged)
        self.assertEqual([], self.github.prs)

    def test_closed_pr_history_cannot_be_reopened_or_its_branch_recreated(self):
        staged = self.stage()
        self.open(staged)
        self.github.prs[0]["state"] = "closed"
        with self.assertRaises(single.PublishError):
            self.open(staged)
        self.git.branches.clear()
        with self.assertRaisesRegex(single.PublishError, "refusing replay"):
            self.stage()

    def test_pr_edit_and_auto_merge_during_final_verification_are_rejected(self):
        staged = self.stage()
        def mutate(descriptor, receipt):
            if self.github.prs:
                self.github.prs[0]["auto_merge"] = {"enabled": True}
            return receipt
        self.fleet_verifier.side_effect = mutate
        with self.assertRaisesRegex(single.PublishError, "auto-merge"):
            self.open(staged)

    def test_publication_deadline_is_bounded_and_expiration_prevents_pr(self):
        staged = self.stage()
        for deadline in (float("inf"), float("nan"), True, -1):
            with self.subTest(deadline=deadline), self.assertRaises(single.PublishError):
                self.open(staged, deadline=deadline)
        self.assertEqual([], self.github.prs)

    def test_remote_ref_creation_race_never_overwrites_another_head(self):
        def race(method, endpoint, payload):
            if method == "POST" and endpoint.endswith("/git/refs"):
                self.git.branches[payload["ref"].removeprefix("refs/heads/")] = "e" * 40
        self.github.before = race
        with self.assertRaisesRegex(single.PublishError, "ref already exists"):
            self.stage()
        self.assertEqual({"e" * 40}, set(self.git.branches.values()))
        self.assertEqual([], self.github.prs)

    def test_iteration_invalidated_between_objects_cannot_create_candidate_ref(self):
        def stale(method, endpoint, payload):
            if method == "POST" and endpoint.endswith("/git/commits"):
                self.current.side_effect = single.PublishError("newer iteration exists")
        self.github.before = stale
        with self.assertRaisesRegex(single.PublishError, "newer iteration"):
            self.stage()
        self.assertEqual({}, self.git.branches)
        self.assertEqual([], self.github.prs)

    def test_second_live_fleet_check_failure_never_opens_draft(self):
        staged = self.stage()
        self.fleet_verifier.side_effect = [self.receipt(staged), single.PublishError("new attempt failed")]
        with self.assertRaisesRegex(single.PublishError, "new attempt failed"):
            self.open(staged)
        self.assertEqual([], self.github.prs)

    def test_final_fleet_failure_does_not_report_publication_success(self):
        staged = self.stage()
        self.fleet_verifier.side_effect = [self.receipt(staged), self.receipt(staged),
                                           single.PublishError("artifact removed")]
        with self.assertRaisesRegex(single.PublishError, "artifact removed"):
            self.open(staged)
        self.assertEqual(1, len(self.github.prs))
        self.assertTrue(self.github.prs[0]["draft"])
        self.assertIsNone(self.github.prs[0]["auto_merge"])

    def test_source_anchor_timestamp_and_parent_are_authenticated(self):
        staged = self.stage()
        anchor_sha = staged["attestation"]["source_anchor"]["sha"]
        original = copy.deepcopy(self.git.commits[anchor_sha])
        self.git.commits[anchor_sha]["parents"] = ["b" * 40]
        with self.assertRaisesRegex(single.PublishError, "ancestry"):
            self.open(staged)
        self.git.commits[anchor_sha] = copy.deepcopy(original)
        self.git.commits[anchor_sha]["committer"]["date"] = "2026-09-24T01:00:00Z"
        with self.assertRaisesRegex(single.PublishError, "timestamp"):
            self.open(staged)
        self.assertEqual([], self.github.prs)

    def test_edited_app_author_or_human_ready_pr_is_not_adopted(self):
        staged = self.stage()
        self.open(staged)
        original = copy.deepcopy(self.github.prs[0])
        for key, value in (("user", {"login": "someone-else"}), ("draft", False),
                           ("body", "human rewrite"), ("title", "human title")):
            self.github.prs[0] = {**copy.deepcopy(original), key: value}
            with self.subTest(key=key), self.assertRaises(single.PublishError):
                self.open(staged)
        self.assertEqual(1, len(self.github.prs))

    def test_source_and_action_topology_changes_cannot_hide_in_a_multi_package_bundle(self):
        for old, new in (("runs-on: ubuntu-24.04-arm", "runs-on: self-hosted"),
                         ("checkout@" + "1" * 40, "checkout@" + "2" * 40)):
            request = copy.deepcopy(self.request)
            request["packages"][1]["proposal"]["edits"][0].update(old=old, new=new)
            with self.subTest(old=old), self.assertRaisesRegex(single.PublishError, "topology|action references"):
                self.stage(request)
        self.assert_no_writes()

    def test_combined_catalog_is_canonical_with_a_fresh_corpus_digest(self):
        staged = self.stage()
        final = self.git.commits[staged["candidate"]["candidate_sha"]]
        raw = self.git.blobs[final["entries"][single.CATALOG_PATH][1]]
        catalog = json.loads(raw)
        self.assertEqual(json.dumps(catalog, indent=2, sort_keys=True) + "\n", raw)
        pairs = []
        for record in catalog["records"]:
            pairs.extend(((record["content_path"], record["content_sha256"]),
                          (record["workflow"]["path"], record["workflow"]["sha256"])))
        self.assertEqual(single.bindings.catalog_validator.calculate_corpus_sha256(pairs),
                         catalog["corpus"]["corpus_sha256"])

    def test_fleet_data_does_not_leak_into_pr_prose(self):
        staged = self.stage()
        receipt = self.receipt(staged)
        receipt["fleet_evidence"]["diagnosis"] = "PRIVATE_FLEET_LOG https://private.invalid/internal"
        self.open(staged, receipt)
        self.assertNotIn("PRIVATE_FLEET_LOG", self.github.prs[0]["body"])
        self.assertNotIn("private.invalid", self.github.prs[0]["body"])

    def test_descriptor_identity_requires_exact_types_and_branch(self):
        descriptor = self.stage()["candidate"]
        for key, value in (("schema_version", True), ("iteration", True), ("iteration", 4),
                           ("branch", "main"), ("candidate_sha", fixtures.BASE),
                           ("cycle_id", "100-1/../main"), ("unexpected", "field")):
            with self.subTest(key=key), self.assertRaises((ValueError, single.PublishError)):
                bundle.validate_descriptor({**descriptor, key: value})

    def test_real_original_policy_independently_admits_both_packages(self):
        for item in self.request["packages"]:
            context = item["context"]
            context["source_text"] = policy_fixtures.SOURCE.replace("widget", context["package_slug"])
            item["proposal"] = policy_fixtures.proposal()
            item["proposal"]["edits"][0]["path"] = context["workflow_path"]
        self._install_workflows()
        self.policy = policy_fixtures.policy.validate_proposal
        plan = self.readmit()
        self.assertEqual(2, len(plan["packages"]))
        staged = self.stage(admitted=plan)
        self.assertEqual(staged, self.verify(staged))

    def test_real_policy_rejects_weakening_one_package_despite_other_package_success(self):
        for item in self.request["packages"]:
            context = item["context"]
            context["source_text"] = policy_fixtures.SOURCE.replace("widget", context["package_slug"])
            item["proposal"] = policy_fixtures.proposal()
            item["proposal"]["edits"][0]["path"] = context["workflow_path"]
        self._install_workflows()
        self.policy = policy_fixtures.policy.validate_proposal
        self.request["packages"][1]["proposal"]["edits"][0].update(old="          zeta --self-test", new="          true")
        with self.assertRaises(ValueError):
            self.stage()
        self.assert_no_writes()

    def admission(self):
        payload = {
            "schema_version": 2, "repository": fixtures.REPOSITORY, "base_sha": fixtures.BASE,
            "orchestrator_run_id": 100, "orchestrator_attempt": 1, "context_artifact_id": 400,
            "cycle_id": "100-1", "iteration": 1,
            "previous_feedback_run_id": None, "previous_feedback_artifact_id": None,
            "proposals": [{"package_slug": item["context"]["package_slug"], "context_sha256": "a" * 64,
                           "operations": [{"kind": "prepend_parallelism", "step": 1,
                                           "variable": "MAKEFLAGS", "count": 2}]}
                          for item in self.request["packages"]],
        }
        return {"schema_version": 1, "request": payload, "repairs": copy.deepcopy(self.request["packages"])}

    def test_bridge_admission_export_and_descriptor_share_exact_cycle(self):
        admission = self.admission()
        self.assertEqual(self.request, bundle.from_admission(admission))
        staged = self.stage()
        envelope = bundle.export_receipt(admission, staged)
        self.assertEqual(envelope, bundle._envelope(envelope))
        self.assertEqual({"schema_version", "admission", "staged"}, set(envelope))
        admission["request"]["iteration"] = 2
        admission["request"].update(previous_feedback_run_id=500, previous_feedback_artifact_id=600)
        with self.assertRaisesRegex(single.PublishError, "admitted cycle"):
            bundle.export_receipt(admission, staged)

    def test_exported_envelope_rejects_model_metadata_and_missing_stage(self):
        staged = self.stage()
        envelope = bundle.export_receipt(self.admission(), staged)
        for bad in ({**envelope, "schema_version": True}, {**envelope, "publisher": "spoof"},
                    {**envelope, "staged": {}}, {**envelope, "admission": {"repairs": []}}):
            with self.subTest(bad=bad), self.assertRaises(single.PublishError):
                bundle._envelope(bad)

    def test_readonly_attestor_needs_no_publisher_credentials_and_reapplies_policy(self):
        staged = self.stage()
        envelope = bundle.export_receipt(self.admission(), staged)
        api = Mock()
        api.api.side_effect = lambda endpoint: self.github._api("GET", endpoint)
        before = len([call for call in self.github.calls if call[0] != "GET"])
        self.policy.reset_mock()
        with patch.dict(os.environ, {"GH_TOKEN": "", "SMOKE_REPAIR_APP_SLUG": ""}), patch.object(
            bundle, "_revalidate_admission", return_value=self.request
        ) as current, patch.object(policy_fixtures.policy, "validate_proposal", self.policy):
            result = bundle.attest_candidate(staged["candidate"], envelope, api=api, repository_root=self.root)
        self.assertEqual(staged["candidate"], result)
        self.assertEqual(2, self.policy.call_count)
        self.assertEqual(2, current.call_count)
        self.assertEqual(before, len([call for call in self.github.calls if call[0] != "GET"]))

    def test_readonly_attestor_rejects_source_or_iteration_mismatch(self):
        staged = self.stage()
        envelope = bundle.export_receipt(self.admission(), staged)
        for descriptor in ({**staged["candidate"], "candidate_sha": "e" * 40},
                           {**staged["candidate"], "iteration": 2}):
            with self.subTest(descriptor=descriptor), self.assertRaises(single.PublishError):
                bundle.attest_candidate(descriptor, envelope, api=Mock(), repository_root=self.root)
        with patch.object(bundle, "_revalidate_admission", side_effect=single.PublishError("cycle expired")):
            with self.assertRaisesRegex(single.PublishError, "cycle expired"):
                bundle.attest_candidate(staged["candidate"], envelope, api=Mock(), repository_root=self.root)

    def test_controller_rejects_wrong_workflow_event_or_attempt(self):
        for key, value in (("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_EVENT_NAME", "push"),
                           ("GITHUB_SHA", "f" * 40), ("GITHUB_WORKFLOW_SHA", "e" * 40),
                           ("GITHUB_WORKFLOW_REF", f"{fixtures.REPOSITORY}/.github/workflows/untrusted.yml@refs/heads/main")):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaises(single.PublishError):
                bundle._controller_runtime(self.request)

    def test_readonly_github_adapter_cannot_write(self):
        api = Mock()
        adapter = bundle._ReadOnlyGitHub(api)
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            with self.subTest(method=method), self.assertRaises(single.PublishError):
                adapter._api(method, "repos/example/secret", {})
        api.api.assert_not_called()

    def test_cli_all_modes_use_fixed_reviewed_implementations_and_immutable_outputs(self):
        admission_path = Path(self.temporary.name) / "admission.json"
        admission_path.write_text(json.dumps(self.admission()))
        base = ["--repository-root", str(self.root)]
        admitted_dir = Path(self.temporary.name) / "readmit"
        staged_dir = Path(self.temporary.name) / "staged"
        verify_dir = Path(self.temporary.name) / "verified"
        publish_dir = Path(self.temporary.name) / "published"
        with patch.object(policy_fixtures.policy, "validate_proposal", self.policy), patch.object(
            bundle, "_revalidate_admission", return_value=self.request
        ), patch.object(single.publisher, "GhClient", return_value=self.github), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(0, bundle.main(["readmit", *base, "--admission", str(admission_path),
                                            "--output-dir", str(admitted_dir)]))
            self.assertEqual(0, bundle.main(["stage", *base, "--admission", str(admission_path),
                                            "--admitted", str(admitted_dir / "admitted.json"),
                                            "--output-dir", str(staged_dir)]))
            descriptor = json.loads((staged_dir / "descriptor.json").read_text())
            envelope = json.loads((staged_dir / "bundle-receipt.json").read_text())
            self.assertEqual(descriptor, envelope["staged"]["candidate"])
            self.assertEqual(0, bundle.main(["verify", *base, "--bundle-receipt", str(staged_dir / "bundle-receipt.json"),
                                            "--output-dir", str(verify_dir)]))
            receipt_file = Path(self.temporary.name) / "fleet.json"
            receipt_file.write_text(json.dumps(self.receipt(envelope["staged"])))
            import smoke_repair_fleet
            with patch.object(smoke_repair_fleet, "FleetValidation") as fleet:
                fleet.return_value.verify.side_effect = lambda descriptor, receipt, **kwargs: receipt
                self.assertEqual(0, bundle.main(["open-draft", *base, "--bundle-receipt", str(staged_dir / "bundle-receipt.json"),
                                                "--fleet-receipt", str(receipt_file), "--output-dir", str(publish_dir)]))
            self.assertEqual("created", json.loads((publish_dir / "publication.json").read_text())["status"])
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(1, bundle.main(["stage", *base, "--admission", str(admission_path),
                                                "--admitted", str(admitted_dir / "admitted.json"),
                                                "--output-dir", str(staged_dir)]))
        self.assertEqual(1, len(self.github.prs))

    def test_cli_errors_do_not_echo_sensitive_exception_details(self):
        admission_path = Path(self.temporary.name) / "admission.json"
        admission_path.write_text(json.dumps(self.admission()))
        with patch.object(bundle, "readmit", side_effect=single.PublishError("PRIVATE_ERROR_CANARY")), patch(
            "sys.stderr", new_callable=io.StringIO
        ) as error:
            result = bundle.main(["readmit", "--repository-root", str(self.root), "--admission", str(admission_path),
                                  "--output-dir", str(Path(self.temporary.name) / "out")])
        self.assertEqual(1, result)
        self.assertNotIn("PRIVATE_ERROR_CANARY", error.getvalue())
        self.assert_no_writes()


if __name__ == "__main__":
    unittest.main()
