"""Public cycle wiring contracts; no workflow dispatch or package execution."""

from __future__ import annotations

import ast
from copy import copy, deepcopy
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exact_run_aggregation import _yaml_mapping
from smoke_repair_cycle_bridge import EVENT, FEEDBACK_JOB, FEEDBACK_STEPS, WORKFLOW


ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / WORKFLOW
REQUIREMENTS = ".github/scripts/requirements-exact-run.txt"


def command_lines(step):
    return step.get("run", "").replace("\\\n", " ").splitlines()


def cli_commands(step):
    for line in command_lines(step):
        if line.strip().startswith("python3 -I -B .github/scripts/"):
            yield shlex.split(line.strip())


class CycleWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATH.read_text(encoding="utf-8")
        cls.workflow = _yaml_mapping(cls.source.encode(), WORKFLOW)
        cls.jobs = cls.workflow["jobs"]

    def step(self, job, name):
        matches = [step for step in self.jobs[job]["steps"] if step.get("name") == name]
        self.assertEqual(1, len(matches), (job, name))
        return matches[0]

    def test_only_explicit_authenticated_dispatch_not_push_pr_or_schedule(self):
        self.assertEqual({"repository_dispatch": {"types": [EVENT]}}, self.workflow["on"])
        self.assertEqual({"contents": "read"}, self.workflow["permissions"])
        self.assertEqual({"admit", "stage", "native", "publish", "report"}, set(self.jobs))
        self.assertNotIn("workflow_dispatch", self.workflow["on"])

    def test_disabled_by_default_trusted_main_first_attempt_and_configured_sender(self):
        guard = self.jobs["admit"]["if"]
        for condition in ("github.ref == 'refs/heads/main'", "github.run_attempt == 1",
                          "vars.SMOKE_REPAIR_ENABLED == 'true'", "vars.SMOKE_REPAIR_BRIDGE_BOT_LOGIN != ''",
                          "github.actor == vars.SMOKE_REPAIR_BRIDGE_BOT_LOGIN"):
            self.assertIn(condition, guard)
        for name in ("SMOKE_REPAIR_ENABLED", "SMOKE_REPAIR_BRIDGE_BOT_LOGIN", "SMOKE_REPAIR_BRIDGE_BOT_ID",
                     "SMOKE_REPAIR_APP_BOT_LOGIN", "DASHBOARD_DELIVERY_APP_BOT_LOGIN"):
            self.assertEqual("${{ vars." + name + " }}", self.workflow["env"][name])
        self.assertNotIn("GH_TOKEN", self.workflow["env"])

    def test_serialized_with_existing_publication_without_canceling_valid_work(self):
        self.assertEqual({"group": "smoke-repair-publication", "cancel-in-progress": False, "queue": "max"},
                         self.workflow["concurrency"])
        self.assertNotIn("github.event.client_payload", str(self.workflow["concurrency"]))

    def test_job_graph_prevents_package_only_or_failed_fleet_publication(self):
        self.assertEqual("admit", self.jobs["stage"]["needs"])
        self.assertEqual(["admit", "stage"], self.jobs["native"]["needs"])
        self.assertEqual(["stage", "native"], self.jobs["publish"]["needs"])
        self.assertEqual("needs.native.result == 'success'", self.jobs["publish"]["if"])
        self.assertNotIn("always()", str(self.jobs["publish"]))
        self.assertEqual(["admit", "stage", "native", "publish"], self.jobs["report"]["needs"])
        self.assertNotIn("report", self.jobs["publish"]["needs"])
        self.assertNotIn("smoke_repair_native.py", self.source)
        self.assertNotIn("smoke-repair-package.yml", self.source)

    def test_only_free_hosted_arm_and_original_main_checkout(self):
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertEqual("ubuntu-24.04-arm", job["runs-on"])
                self.assertLessEqual(job["timeout-minutes"], 360)
                self.assertEqual(1, len([step for step in job["steps"]
                                         if step.get("uses", "").startswith("actions/checkout@")]))
                checkout = job["steps"][0]
                self.assertTrue(checkout["uses"].startswith("actions/checkout@"))
                self.assertEqual({"ref": "${{ github.sha }}", "fetch-depth": 0, "persist-credentials": False},
                                 checkout["with"])
        self.assertNotIn("self-hosted", self.source)
        self.assertNotIn("candidate_sha }}", self.source)
        self.assertNotIn("git checkout", self.source)
        self.assertNotIn("git switch", self.source)

    def test_public_workflow_contains_no_model_access_or_private_implementation(self):
        for forbidden in ("Arm-Debug/", "openai", "SPIFFE", "model_token", "production-model", "id-token",
                          "secrets: inherit", "SMOKE_REPAIR_OPENAI_API_KEY", "smoke_repair_model.py"):
            self.assertNotIn(forbidden.casefold(), self.source.casefold())

    def test_permissions_and_delivery_environments_are_separated(self):
        for name in ("admit", "stage", "publish"):
            self.assertEqual({"contents": "read", "actions": "read"}, self.jobs[name]["permissions"])
        self.assertEqual({"contents": "read", "actions": "write"}, self.jobs["native"]["permissions"])
        self.assertEqual({"contents": "read", "issues": "write"}, self.jobs["report"]["permissions"])
        for name in ("stage", "publish"):
            self.assertEqual("smoke-repair-delivery", self.jobs[name]["environment"])
        for name in ("admit", "native", "report"):
            self.assertNotIn("environment", self.jobs[name])
            self.assertNotIn("secrets.", str(self.jobs[name]))
            self.assertNotIn("repair_token", str(self.jobs[name]))
            self.assertNotIn("SMOKE_REPAIR_APP_SLUG", str(self.jobs[name]))

    def test_app_tokens_are_repository_scoped_and_not_generated_data_credentials(self):
        for job in ("stage", "publish"):
            mint = self.step(job, "Mint dedicated repair App token")
            inputs = mint["with"]
            self.assertEqual("${{ secrets.SMOKE_REPAIR_APP_ID }}", inputs["app-id"])
            self.assertEqual("${{ secrets.SMOKE_REPAIR_APP_PRIVATE_KEY }}", inputs["private-key"])
            self.assertEqual("${{ github.repository_owner }}", inputs["owner"])
            self.assertEqual("${{ github.event.repository.name }}", inputs["repositories"])
            self.assertEqual({"permission-contents": "write", "permission-pull-requests": "write",
                              "permission-workflows": "write", "permission-actions": "read"},
                             {key: value for key, value in inputs.items() if key.startswith("permission-")})
            self.assertNotIn("skip-token-revoke", inputs)
        self.assertNotIn("DASHBOARD_DELIVERY_APP_PRIVATE_KEY", self.source)
        for job in self.jobs.values():
            for step in job["steps"]:
                if "secrets." in str(step):
                    self.assertEqual("repair_token", step.get("id"))

    def test_runtime_tokens_only_reach_their_expected_commands(self):
        seen_publishers = 0
        for job in self.jobs.values():
            for step in job["steps"]:
                token = step.get("env", {}).get("GH_TOKEN")
                if token == "${{ steps.repair_token.outputs.token }}":
                    seen_publishers += 1
                    commands = list(cli_commands(step))
                    self.assertEqual(1, len(commands))
                    self.assertEqual(".github/scripts/smoke_repair_bundle.py", commands[0][3])
                    self.assertIn(commands[0][4], {"stage", "open-draft"})
                elif token is not None:
                    self.assertEqual("${{ github.token }}", token)
        self.assertEqual(2, seen_publishers)

    def test_upstream_metadata_credential_is_step_scoped_to_researching_commands(self):
        key = "SMOKE_REPAIR_UPSTREAM_READ_TOKEN"
        expected = {
            ("admit", "Authenticate sender original failures and iteration evidence"),
            ("stage", "Reauthenticate and independently readmit before write credentials"),
            ("stage", "Stage one immutable source anchor and combined bindings"),
            ("native", "Run complete candidate fleet and build candidate summary"),
            ("native", "Build sanitized authenticated cycle feedback"),
            ("publish", "Readmit bundle and check receipt identity before delivery credentials"),
            ("publish", "Recheck exact candidate and open only a draft PR"),
        }
        commands = {
            ("smoke_repair_cycle_bridge.py", "admit"),
            ("smoke_repair_cycle_bridge.py", "feedback"),
            ("smoke_repair_bundle.py", "readmit"),
            ("smoke_repair_bundle.py", "stage"),
            ("smoke_repair_bundle.py", "open-draft"),
            ("smoke_repair_fleet.py", "run"),
        }
        observed, seen_commands = set(), set()
        self.assertNotIn(key, self.workflow.get("env", {}))
        for job_name, job in self.jobs.items():
            self.assertNotIn(key, job.get("env", {}))
            for step in job["steps"]:
                requires_research = {(Path(command[3]).name, command[4]) for command in cli_commands(step)} & commands
                inline_readmission = (job_name, step["name"]) in {
                    ("stage", "Reauthenticate and independently readmit before write credentials"),
                    ("publish", "Readmit bundle and check receipt identity before delivery credentials"),
                }
                token = step.get("env", {}).get(key)
                self.assertEqual(bool(requires_research) or inline_readmission, token is not None, (job_name, step["name"]))
                if token is None:
                    continue
                observed.add((job_name, step["name"]))
                seen_commands.update(requires_research)
                self.assertEqual("${{ github.token }}", token)
                self.assertEqual("read", job["permissions"]["contents"])
                self.assertNotIn("uses", step)
                if not inline_readmission:
                    self.assertNotIn(key, step["run"])
                else:
                    self.assertIn('research_session(metadata_token=os.environ.get("SMOKE_REPAIR_UPSTREAM_READ_TOKEN")', step["run"])
        self.assertEqual(expected, observed)
        self.assertEqual(commands, seen_commands)

    def test_upstream_research_never_receives_the_repair_app_write_token(self):
        for job, name in (("stage", "Stage one immutable source anchor and combined bindings"),
                          ("publish", "Recheck exact candidate and open only a draft PR")):
            env = self.step(job, name)["env"]
            self.assertEqual("${{ steps.repair_token.outputs.token }}", env["GH_TOKEN"])
            self.assertEqual("${{ github.token }}", env["SMOKE_REPAIR_UPSTREAM_READ_TOKEN"])
            self.assertNotEqual(env["GH_TOKEN"], env["SMOKE_REPAIR_UPSTREAM_READ_TOKEN"])
            self.assertNotIn("secrets.", env["SMOKE_REPAIR_UPSTREAM_READ_TOKEN"])
        for job in self.jobs.values():
            for step in job["steps"]:
                if "uses" in step or "Install pinned" in step["name"] or "catalog" in step["name"].casefold():
                    self.assertNotIn("SMOKE_REPAIR_UPSTREAM_READ_TOKEN", step.get("env", {}))
        self.assertNotIn("SMOKE_REPAIR_UPSTREAM_READ_TOKEN", str(self.jobs["report"]))
        gate = self.step("native", "Enforce complete candidate fleet success")
        self.assertNotIn("SMOKE_REPAIR_UPSTREAM_READ_TOKEN", gate.get("env", {}))

    def test_sender_and_identity_outputs_come_from_validated_event_file(self):
        step = self.step("admit", "Authenticate sender original failures and iteration evidence")
        self.assertIn('--event "$GITHUB_EVENT_PATH"', step["run"])
        self.assertIn("validate_payload(document[\"request\"], os.environ[\"GITHUB_SHA\"])", step["run"])
        self.assertIn('os.environ["GITHUB_OUTPUT"]', step["run"])
        self.assertEqual("${{ steps.admit.outputs.cycle_id }}", self.jobs["admit"]["outputs"]["cycle_id"])
        self.assertEqual("${{ steps.admit.outputs.iteration }}", self.jobs["admit"]["outputs"]["iteration"])
        self.assertNotIn("github.event.client_payload", self.source)
        for job in self.jobs.values():
            for step in job["steps"]:
                self.assertNotIn("${{", step.get("run", ""))

    def test_wrapped_dispatch_preserves_admission_and_validated_workflow_outputs(self):
        import smoke_repair_cycle_bridge as bridge
        from test_smoke_repair_cycle_bridge import legacy, payload
        event, environment = legacy.event(), legacy.environment()
        request = payload()
        event.update(action=EVENT, client_payload={"repair": request})
        environment["GITHUB_WORKFLOW_REF"] = f"{bridge.REPOSITORY}/{WORKFLOW}@refs/heads/main"
        self.assertEqual(11, len(request))
        self.assertEqual({"repair"}, set(event["client_payload"]))
        self.assertLessEqual(len(json.dumps(event["client_payload"]).encode()), 65535)
        admission = {"schema_version": 1, "request": request, "repairs": []}
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            event_path, outputs = temporary / "event.json", temporary / "outputs"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            environment.update(GITHUB_EVENT_PATH=str(event_path), GITHUB_OUTPUT=str(outputs))
            destination = temporary / "admission"
            with patch.dict(os.environ, environment, clear=True), patch.object(
                bridge, "GitHub"
            ), patch.object(bridge, "admit_cycle", return_value=admission) as admit, patch(
                "sys.stdout", new_callable=io.StringIO
            ):
                self.assertEqual(0, bridge.main(["admit", "--event", str(event_path),
                    "--repository-root", str(ROOT), "--output-dir", str(destination)]))
                self.assertEqual(request, admit.call_args.args[0])
                admitted_path = destination / "admission.json"
                self.assertEqual(admission, json.loads(admitted_path.read_text()))
                source = self.step("admit", "Authenticate sender original failures and iteration evidence")["run"]
                bodies = re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", source, re.DOTALL)
                self.assertEqual(1, len(bodies))
                with patch.object(sys, "argv", ["-", str(admitted_path)]), patch.object(sys, "path", sys.path.copy()):
                    exec(compile(bodies[0], "trusted-cycle-admission-outputs", "exec"), {"__name__": "__main__"})
            self.assertEqual("cycle_id=123456-1\niteration=1\n", outputs.read_text())

    def test_dispatch_transport_rejects_unwrapped_alternate_and_mixed_envelopes(self):
        import smoke_repair_cycle_bridge as bridge
        from test_smoke_repair_cycle_bridge import legacy, payload
        event, environment = legacy.event(), legacy.environment()
        environment["GITHUB_WORKFLOW_REF"] = f"{bridge.REPOSITORY}/{WORKFLOW}@refs/heads/main"
        variants = [payload(), {"request": payload()}, {"repair": payload(), "request": payload()},
                    {"repair": {"repair": payload()}}, {"repair": None}, {"repair": payload(), "iteration": 1}]
        for wrapper in variants:
            with self.subTest(wrapper=wrapper), self.assertRaises(ValueError):
                bridge.validate_event({**event, "action": EVENT, "client_payload": wrapper}, environment)

    def test_policy_syntax_and_catalog_preflight_precede_write_credentials(self):
        job = self.jobs["stage"]
        names = [step["name"] for step in job["steps"]]
        check = self.step("stage", "Reauthenticate and independently readmit before write credentials")
        self.assertIn("smoke_repair_cycle_bridge.py admit", check["run"])
        self.assertIn("smoke_repair_bundle.py readmit", check["run"])
        self.assertIn("cmp ", check["run"])
        self.assertIn("from smoke_repair_pipeline import admit", check["run"])
        self.assertIn('admit(repair["context"], repair["proposal"])', check["run"])
        catalog = self.step("stage", "Validate exact reviewed catalog before delivery credentials")
        self.assertIn("--revision", catalog["run"])
        self.assertIn("--hugo-binary", catalog["run"])
        self.assertIn("sha256sum --check --strict", catalog["run"])
        self.assertRegex(catalog["env"]["HUGO_ARM64_ARCHIVE_SHA256"], r"^[a-f0-9]{64}$")
        for name in (check["name"], catalog["name"]):
            self.assertLess(names.index(name), names.index("Mint dedicated repair App token"))

    def test_actions_and_parser_dependencies_are_pinned(self):
        for job in self.jobs.values():
            parser = [step for step in job["steps"] if step["name"] == "Install pinned workflow parser"]
            self.assertEqual(1, len(parser))
            for fragment in ("--no-deps", "--only-binary=:all:", "--require-hashes", REQUIREMENTS):
                self.assertIn(fragment, parser[0]["run"])
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"^actions/[a-z0-9-]+@[0-9a-f]{40}$")

    def test_artifact_transfers_use_exact_this_run_ids(self):
        for job in self.jobs.values():
            for step in job["steps"]:
                action = step.get("uses", "")
                if action.startswith("actions/download-artifact@"):
                    options = step["with"]
                    self.assertRegex(options["artifact-ids"], r"^\$\{\{ needs\.(admit|stage|native)\.outputs\.artifact_id \}\}$")
                    self.assertEqual({"artifact-ids", "path", "merge-multiple"}, set(options))
                    self.assertTrue(options["merge-multiple"])
                elif action.startswith("actions/upload-artifact@"):
                    self.assertEqual("error", step["with"]["if-no-files-found"])
                    self.assertEqual(30, step["with"]["retention-days"])
                    self.assertNotIn("overwrite", step["with"])
                    self.assertNotIn("include-hidden-files", step["with"])

    def test_feedback_producer_matches_authenticated_bridge_contract_exactly(self):
        job = self.jobs["native"]
        self.assertEqual(FEEDBACK_JOB, job["name"])
        names = [step["name"] for step in job["steps"]]
        for name in FEEDBACK_STEPS:
            self.assertEqual(1, names.count(name))
        collection = names.index("Run complete candidate fleet and build candidate summary")
        creation = names.index("Build sanitized authenticated cycle feedback")
        receipt = names.index("Preserve complete candidate fleet receipt")
        upload = names.index("Preserve authenticated cycle feedback")
        enforcement = names.index("Enforce complete candidate fleet success")
        self.assertLess(collection, creation)
        self.assertLess(creation, receipt)
        self.assertLess(receipt, upload)
        self.assertLess(upload, enforcement)
        artifact = job["steps"][upload]["with"]
        self.assertEqual("smoke-repair-cycle-feedback-${{ needs.admit.outputs.cycle_id }}-${{ needs.admit.outputs.iteration }}",
                         artifact["name"])
        self.assertEqual("${{ runner.temp }}/repair-cycle-feedback/feedback.json", artifact["path"])
        self.assertNotIn("\n", artifact["path"])

    def test_failures_are_not_masked_and_incomplete_receipts_are_not_uploaded(self):
        for job in self.jobs.values():
            self.assertNotIn("continue-on-error", job)
            for step in job["steps"]:
                self.assertNotIn("continue-on-error", step)
                self.assertNotIn("if", step)
                self.assertNotRegex(step.get("run", ""), r"\|\|\s*(true|:)|set \+e|exit 0")
        enforce = self.step("native", "Enforce complete candidate fleet success")
        self.assertIn("smoke_repair_cycle_bridge.py enforce", enforce["run"])
        self.assertIn('--bundle-receipt "$RUNNER_TEMP/repair-cycle-stage/bundle-receipt.json"', enforce["run"])
        self.assertIn('--fleet-receipt "$RUNNER_TEMP/repair-cycle-fleet/receipt.json"', enforce["run"])
        self.assertNotIn("--feedback", enforce["run"])
        self.assertNotIn("GH_TOKEN", enforce.get("env", {}))

    def test_fleet_run_and_feedback_verify_budget_fit_hosted_runner_limit(self):
        from smoke_repair_fleet import MAX_SECONDS, VERIFY_SECONDS
        self.assertLess(MAX_SECONDS + VERIFY_SECONDS, self.jobs["native"]["timeout-minutes"] * 60)
        self.assertLess(self.jobs["native"]["timeout-minutes"], 360)
        self.assertEqual(70, self.jobs["publish"]["timeout-minutes"])
        self.assertGreater(self.jobs["publish"]["timeout-minutes"] * 60, VERIFY_SECONDS * 2)
        self.assertGreaterEqual(self.jobs["stage"]["timeout-minutes"], 30)

    def test_quota_aware_admission_and_stage_deadlines_fit_jobs_and_app_lifetime(self):
        from smoke_repair_cycle_bridge import ADMISSION_SECONDS
        from smoke_repair_fleet import VERIFY_SECONDS
        setup_seconds = 15 * 60
        self.assertEqual(90, self.jobs["admit"]["timeout-minutes"])
        self.assertGreaterEqual(self.jobs["admit"]["timeout-minutes"] * 60, ADMISSION_SECONDS + setup_seconds)
        stage = self.step("stage", "Stage one immutable source anchor and combined bindings")
        app_step_seconds = stage["timeout-minutes"] * 60
        self.assertGreater(app_step_seconds, VERIFY_SECONDS)
        self.assertLess(app_step_seconds, 60 * 60)
        self.assertEqual(125, self.jobs["stage"]["timeout-minutes"])
        self.assertGreaterEqual(self.jobs["stage"]["timeout-minutes"] * 60,
                                ADMISSION_SECONDS + app_step_seconds + setup_seconds)
        names = [step["name"] for step in self.jobs["stage"]["steps"]]
        self.assertEqual(names.index("Mint dedicated repair App token") + 1, names.index(stage["name"]))

    def test_publication_readmits_before_mint_and_verifies_live_fleet_only_under_app(self):
        names = [step["name"] for step in self.jobs["publish"]["steps"]]
        check = self.step("publish", "Readmit bundle and check receipt identity before delivery credentials")
        self.assertIn("admitted = readmit(", check["run"])
        self.assertIn('receipt["descriptor"] != descriptor', check["run"])
        self.assertIn('_json(audit) != _json(expected)', check["run"])
        self.assertNotIn("FleetValidation", check["run"])
        self.assertNotIn("smoke_repair_fleet.py verify", self.source)
        self.assertNotIn("attest_candidate(", check["run"])
        self.assertNotIn("GitHub(", check["run"])
        self.assertEqual("${{ github.token }}", check["env"]["GH_TOKEN"])
        self.assertLess(names.index(check["name"]), names.index("Mint dedicated repair App token"))
        publish = self.step("publish", "Recheck exact candidate and open only a draft PR")
        self.assertIn("smoke_repair_bundle.py open-draft", publish["run"])
        self.assertIn("--bundle-receipt", publish["run"])
        self.assertIn("--fleet-receipt", publish["run"])
        self.assertGreater(names.index(publish["name"]), names.index("Mint dedicated repair App token"))
        for forbidden in ("gh pr merge", "gh pr review", "--force", "production", "aws s3", "aws cloudfront"):
            self.assertNotIn(forbidden, self.source)

    def run_publication_preflight(self, root, envelope, receipt):
        source = self.step("publish", "Readmit bundle and check receipt identity before delivery credentials")["run"]
        bodies = re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", source, re.DOTALL)
        self.assertEqual(1, len(bodies))
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            for relative, document in (("repair-cycle-stage/bundle-receipt.json", envelope),
                                       ("repair-cycle-fleet/receipt.json", receipt)):
                path = temporary / relative
                path.parent.mkdir()
                path.write_text(json.dumps(document), encoding="utf-8")
            with patch.dict(os.environ, {"RUNNER_TEMP": directory}), patch.object(
                Path, "cwd", return_value=root
            ), patch.object(sys, "path", sys.path.copy()):
                exec(compile(bodies[0], "trusted-cycle-publication-preflight", "exec"), {"__name__": "__main__"})

    def test_actual_inline_stage_admits_ten_repairs_with_read_only_metadata_session(self):
        import smoke_repair_bridge as bridge
        import smoke_repair_native as native
        import smoke_repair_policy as policy
        import smoke_repair_upstream as research
        import test_smoke_repair_upstream as upstream
        from test_smoke_repair_pipeline import SOURCE, context

        token = "ghs_" + "r" * 36
        repairs, clients = [], []
        for index in range(10):
            slug = f"widget{index}"
            source = SOURCE.replace("https://example.org/widget-1.2.3.tar.gz", upstream.OLD_URL)
            source = source.replace("test-widget:", f"test-{slug}:").replace(
                "package_slug=widget", f"package_slug={slug}")
            trusted = context(source)
            trusted.update(package_slug=slug, workflow_path=f".github/workflows/test-{slug}.yml",
                           called_job=f"test-{slug}")
            with research.research_session(client=upstream.FakeClient()):
                choice = research.research_downloads(trusted)["candidates"][0]
                operation = {"kind": "github_release_download",
                             **{key: choice[key] for key in ("step", "line", "research_id")}}
                proposal = bridge.compile_proposal(trusted, [operation])
            repairs.append({"context": trusted, "proposal": proposal})

        class BudgetClient(upstream.FakeClient):
            def __init__(self, *, metadata_token=None):
                super().__init__()
                self.authenticated = metadata_token == token
                clients.append(self)

            def get_json(self, path):
                research._REQUEST_BUDGET.take(self.authenticated)
                return super().get_json(path)

            def asset_sha256(self, path, size):
                research._REQUEST_BUDGET.take(False)
                return super().asset_sha256(path, size)

        source = self.step("stage", "Reauthenticate and independently readmit before write credentials")["run"]
        bodies = re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", source, re.DOTALL)
        self.assertEqual(1, len(bodies))
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "admission.json"
            document.write_text(json.dumps({"repairs": repairs}), encoding="utf-8")
            budget = research._RequestBudget()
            with patch.dict(os.environ, {"SMOKE_REPAIR_UPSTREAM_READ_TOKEN": token}), \
                    patch.object(sys, "argv", ["-", str(document)]), \
                    patch.object(sys, "path", sys.path.copy()), \
                    patch.object(research, "_REQUEST_BUDGET", budget), \
                    patch.object(research, "_DEFAULT_SESSION", research.ResearchSession()), \
                    patch.object(research, "GitHubReleases", side_effect=BudgetClient), \
                    patch.object(policy, "validate_proposal", wraps=policy.validate_proposal) as validate, \
                    patch.object(native, "derive_native_contract", wraps=native.derive_native_contract) as derive:
                exec(compile(bodies[0], "trusted-cycle-stage-preflight", "exec"), {"__name__": "__main__"})
        self.assertEqual(10, validate.call_count)
        self.assertEqual(10, derive.call_count)
        self.assertTrue(clients and all(client.authenticated for client in clients))
        self.assertGreater(budget.counts[True], research.UNAUTHENTICATED_REQUESTS)
        self.assertEqual(10, budget.counts[False])

    def preflight_fixture(self):
        import smoke_repair_bundle as bundle
        from smoke_repair_fleet import RECEIPT_KEYS
        from test_smoke_repair_bundle import BundleTests
        case = BundleTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        staged = case.stage()
        envelope = bundle.export_receipt(case.admission(), staged)
        receipt = {key: None for key in RECEIPT_KEYS}
        receipt.update(schema_version=1, descriptor=staged["candidate"], status="success",
                       kind="smoke-repair-candidate-fleet", publishing=False)
        case.policy.reset_mock()
        self.enterContext(patch("smoke_repair_policy.validate_proposal", case.policy))
        return case, envelope, receipt

    def test_pre_token_preflight_readmits_every_package_without_remote_fleet_reads(self):
        case, envelope, receipt = self.preflight_fixture()
        before = len(case.github.calls)
        with patch("smoke_repair_fleet.FleetValidation", side_effect=AssertionError("App must own live fleet reads")):
            self.run_publication_preflight(case.root, envelope, receipt)
        self.assertEqual(2, case.policy.call_count)
        self.assertEqual(before, len(case.github.calls))
        self.assertEqual([], case.github.prs)

    def test_pre_token_preflight_rejects_failed_mismatched_or_spoofed_receipts(self):
        case, envelope, receipt = self.preflight_fixture()
        changes = (
            lambda bundle, fleet: fleet.update(status="failure"),
            lambda bundle, fleet: fleet.update(schema_version=True),
            lambda bundle, fleet: fleet["descriptor"].update(candidate_sha="f" * 40),
            lambda bundle, fleet: bundle["staged"]["attestation"].update(source_anchor=None),
            lambda bundle, fleet: bundle["staged"]["attestation"].update(plan_digest="f" * 64),
            lambda bundle, fleet: bundle["staged"]["attestation"]["publisher"].update(run_id=999),
        )
        for change in changes:
            changed_bundle, changed_receipt = deepcopy(envelope), deepcopy(receipt)
            change(changed_bundle, changed_receipt)
            with self.subTest(change=change), patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
                self.run_publication_preflight(case.root, changed_bundle, changed_receipt)
            self.assertEqual(1, error.exception.code)
        self.assertEqual([], case.github.prs)

    def test_iteration_three_native_feedback_and_publication_use_separate_real_quota_pools(self):
        import smoke_repair_bundle as bundle
        import smoke_repair_cycle_bridge as bridge
        import smoke_repair_fleet as fleet
        from smoke_repair_session import VerificationSession
        from test_smoke_repair_session import CycleBudgetTests, PREFIX

        # Reuse the real 22-batch artifact/ancestor verifiers. This budget
        # fixture mocks Git/policy, covered independently by preflight tests.
        case = CycleBudgetTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.api.failures = {}
        case.api.queue_until = case.started + 55 * 60
        envelope = case.envelopes[3]
        descriptor = envelope["staged"]["candidate"]
        producer = envelope["staged"]["attestation"]["publisher"]
        stamp = datetime.fromtimestamp(case.epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        plan = {"request_digest": "a" * 64, "policy_version": "1", "packages": []}
        anchor = {"sha": "e" * 40, "tree_sha": "d" * 40, "verified_at": stamp}
        envelope["staged"]["attestation"] = bundle._attestation(plan, producer, "c" * 40, anchor)
        bundle.readmit.return_value = plan
        receipt = case.native()
        self.assertEqual("success", receipt["status"])
        self.assertEqual(22, receipt["summary"]["batch_count"])
        native_charged = case.api.charged
        native_wait = case.api.elapsed - case.started
        endpoint = PREFIX + "/actions/runs/503"
        case.api.responses[endpoint].update(status="in_progress", conclusion=None)
        case.api.responses[endpoint + "/attempts/1"].update(status="in_progress", conclusion=None)
        case.api.responses[endpoint + "/attempts/1/jobs?per_page=100"] = [{"total_count": 1, "jobs": [{
            "id": 800003, "run_id": 503, "run_attempt": 1, "name": bridge.FEEDBACK_JOB,
            "head_sha": descriptor["base_sha"], "status": "in_progress", "conclusion": None,
            "started_at": receipt["started_at"], "steps": [{"name": bridge.NATIVE_STEP,
                "status": "completed", "conclusion": "success", "started_at": receipt["started_at"],
                "completed_at": receipt["completed_at"]}],
        }]}]
        environment = {"GITHUB_RUN_ID": "503", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_JOB": "native",
                       "GITHUB_WORKFLOW_REF": producer["workflow_ref"], "SMOKE_REPAIR_APP_BOT_LOGIN": "repair[bot]"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, environment):
            root = Path(directory)
            bundle_path, fleet_path = root / "bundle.json", root / "fleet.json"
            bundle_path.write_text(json.dumps(envelope), encoding="utf-8")
            fleet_path.write_text(json.dumps(receipt), encoding="utf-8")
            flags = ["--repository-root", str(case.root), "--bundle-receipt", str(bundle_path),
                     "--fleet-receipt", str(fleet_path)]
            # A new CLI process still shares the native job's used quota.
            with patch.object(bridge, "GitHub", return_value=case.api), patch.object(
                bridge.time, "time", side_effect=case.api.now
            ), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(0, bridge.main(["feedback", *flags, "--output-dir", str(root / "feedback")]))
                self.assertEqual(0, bridge.main(["enforce", *flags]))
            feedback = json.loads((root / "feedback/feedback.json").read_text())
            self.assertEqual(receipt, feedback["fleet_receipt"])
            self.assertEqual(case.context, feedback["contexts"][0])
            self.assertLessEqual(case.api.charged - native_charged, 10)
            self.assertEqual(native_wait, case.api.elapsed - case.started)
            self.run_publication_preflight(case.root, envelope, receipt)
        github_usage = (case.api.charged, case.api.used, case.api.elapsed)
        self.assertLessEqual(case.api.used, 1000)

        # Independent installation token, not a reset of the original quota.
        app = copy(case.api)
        app.limit, app.used, app.charged = 5000, 0, 0
        app.calls, app.waits = [], []
        session = VerificationSession(wall_clock=app.now)
        verifier = fleet.FleetValidation(api=app, wall_clock=app.now, clock=lambda: app.elapsed,
                                        sleep=app.sleep, session=session, timeout_seconds=fleet.VERIFY_SECONDS)
        for _ in range(3):
            verified = verifier.verify(descriptor, receipt, repository_root=case.root,
                                       bundle_receipt=envelope, attest_candidate=bundle.attest_candidate)
            self.assertEqual(receipt, verified)
        self.assertLess(app.charged, 5000)
        self.assertEqual([], app.waits)
        self.assertEqual(github_usage, (case.api.charged, case.api.used, case.api.elapsed))
        # Even a cached publication check must reject a rerun after native.
        first_run = receipt["history"][0][0]["run_id"]
        app.runs[first_run]["run_attempt"] = 2
        with self.assertRaises(bridge.ContractError):
            verifier.verify(descriptor, receipt, repository_root=case.root,
                            bundle_receipt=envelope, attest_candidate=bundle.attest_candidate)
        print(f"\nworkflow iteration3: native+feedback {case.api.charged} GitHub requests, "
              f"{case.api.used}/1000 current hour, {native_wait:g}s wait; "
              f"independent publication {app.charged}/5000 App requests")

    def test_cli_output_directories_are_new_and_never_precreated(self):
        for job in self.jobs.values():
            script = "\n".join(step.get("run", "") for step in job["steps"])
            directories = re.findall(r'--output-dir "([^"]+)"', script)
            self.assertEqual(len(directories), len(set(directories)))
            for directory in directories:
                self.assertNotIn(f'mkdir -p "{directory}"', script)
                self.assertTrue(directory.startswith("$RUNNER_TEMP/repair-cycle-"))

    def test_actual_cli_parsers_accept_every_workflow_flag(self):
        for job_name, job in self.jobs.items():
            for step in job["steps"]:
                for command in cli_commands(step):
                    with self.subTest(job=job_name, command=command):
                        source = ast.parse((ROOT / command[3]).read_text(encoding="utf-8"))
                        flags = {argument.value for node in ast.walk(source)
                                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                                 and node.func.attr == "add_argument"
                                 for argument in node.args if isinstance(argument, ast.Constant)
                                 and isinstance(argument.value, str) and argument.value.startswith("--")}
                        supplied = {word for word in command[5:] if word.startswith("--")}
                        self.assertFalse(supplied - flags, f"unsupported CLI flags: {supplied - flags}")
                        self.assertIn("--repository-root", supplied)

    def test_all_shell_and_inline_python_are_syntax_valid_without_execution(self):
        for job_name, job in self.jobs.items():
            for step in job["steps"]:
                if "run" not in step:
                    continue
                with self.subTest(job=job_name, step=step["name"]):
                    result = subprocess.run(["bash", "--noprofile", "--norc", "-n"], input=step["run"],
                                            text=True, capture_output=True, timeout=10, check=False)
                    self.assertEqual(0, result.returncode, result.stderr)
                    for body in re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", step["run"], re.DOTALL):
                        ast.parse(body)

    def test_workflow_cli_entrypoints_import_under_actual_isolated_python_flags(self):
        scripts = {command[3] for job in self.jobs.values() for step in job["steps"]
                   for command in cli_commands(step)}
        for script in sorted(scripts):
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / script), "--help"],
                                        capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("--repository-root", result.stdout)

    def test_post_upload_gate_uses_same_receipts_without_another_network_validation(self):
        import smoke_repair_cycle_bridge as bridge
        import smoke_repair_fleet as fleet
        descriptor = {"schema_version": 1, "repository": "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm",
                      "base_sha": "a" * 40, "candidate_sha": "b" * 40, "cycle_id": "100-1", "iteration": 1,
                      "branch": "automation/smoke-repair-cycle/100-1/iteration-1"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle_path, fleet_path = root / "bundle.json", root / "fleet.json"
            bundle_path.write_text(json.dumps({"staged": {"candidate": descriptor}}))
            arguments = ["enforce", "--repository-root", str(ROOT), "--bundle-receipt", str(bundle_path),
                         "--fleet-receipt", str(fleet_path)]
            for status, expected in (("success", 0), ("failure", 1), ("incomplete", 1), (None, 1)):
                fleet_path.write_text(json.dumps({"descriptor": descriptor, "publishing": False,
                                                 "kind": "smoke-repair-candidate-fleet", "status": status}))
                with self.subTest(status=status), patch.object(
                    fleet, "FleetValidation", side_effect=AssertionError("local gate must not rerun fleet verification")
                ), patch.object(bridge, "GitHub", side_effect=AssertionError("local gate must not access GitHub")):
                    self.assertEqual(expected, bridge.main(arguments))
            fleet_path.write_text(json.dumps({"descriptor": {**descriptor, "candidate_sha": "c" * 40},
                                             "publishing": False, "kind": "smoke-repair-candidate-fleet", "status": "success"}))
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(1, bridge.main(arguments))

    def test_report_always_runs_only_for_enabled_trusted_first_attempt_sender(self):
        job = self.jobs["report"]
        for condition in ("always()", "github.event_name == 'repository_dispatch'", "github.ref == 'refs/heads/main'",
                          "github.run_attempt == 1", "vars.SMOKE_REPAIR_ENABLED == 'true'",
                          "vars.SMOKE_REPAIR_BRIDGE_BOT_LOGIN != ''", "vars.SMOKE_REPAIR_BRIDGE_BOT_ID != ''",
                          "github.actor == vars.SMOKE_REPAIR_BRIDGE_BOT_LOGIN",
                          "github.actor_id == vars.SMOKE_REPAIR_BRIDGE_BOT_ID"):
            self.assertIn(condition, job["if"])
        self.assertNotIn("needs.native.result == 'success'", job["if"])
        self.assertNotIn("needs.publish.result == 'success'", job["if"])
        self.assertEqual(5, job["timeout-minutes"])
        self.assertNotIn("outputs", job)
        for forbidden in ("secrets.", "repair_token", "create-github-app-token", "download-artifact",
                          "open-draft", "smoke_repair_fleet.py", "environment"):
            self.assertNotIn(forbidden, str(job))

    def test_report_inputs_are_structured_environment_data_and_success_only_pr_url(self):
        step = self.step("report", "Notify owner of truthful candidate outcome")
        self.assertEqual("${{ toJSON(needs) }}", step["env"]["SMOKE_REPAIR_CYCLE_NEEDS"])
        self.assertEqual("${{ vars.SMOKE_NOTIFICATION_LOGIN }}", step["env"]["RECIPIENT"])
        self.assertEqual("${{ needs.admit.outputs.cycle_id }}", step["env"]["CYCLE_ID"])
        self.assertEqual("${{ needs.admit.outputs.iteration }}", step["env"]["ITERATION"])
        self.assertEqual("${{ needs.native.outputs.feedback_artifact_id }}", step["env"]["FEEDBACK_ARTIFACT_ID"])
        self.assertEqual("${{ needs.publish.result == 'success' && needs.publish.outputs.pull_request_url || '' }}",
                         step["env"]["SMOKE_REPAIR_PR_URL"])
        self.assertIn('decode_json(os.environ["SMOKE_REPAIR_CYCLE_NEEDS"])', step["run"])
        self.assertNotIn("${{", step["run"])
        self.assertNotIn("eval(", step["run"])

    def run_notification(self, results, *, cycle_id="100-1", iteration="1", url="", recipient="owner", raw_needs=None,
                         feedback_artifact_id=""):
        from smoke_recovery import GitHub
        from unittest.mock import Mock
        source = self.step("report", "Notify owner of truthful candidate outcome")["run"]
        bodies = re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", source, re.DOTALL)
        self.assertEqual(1, len(bodies))
        code = compile(bodies[0], "trusted-cycle-report-step", "exec")
        needs = raw_needs if raw_needs is not None else {name: {"result": result} for name, result in results.items()}
        environment = {"REPOSITORY": "ArmDeveloperEcosystem/ecosystem-dashboard-for-arm",
                       "GITHUB_RUN_ID": "12345", "GITHUB_RUN_ATTEMPT": "1", "RECIPIENT": recipient,
                       "CYCLE_ID": cycle_id, "ITERATION": iteration,
                       "FEEDBACK_ARTIFACT_ID": feedback_artifact_id,
                       "SMOKE_REPAIR_CYCLE_NEEDS": json.dumps(needs), "SMOKE_REPAIR_PR_URL": url}
        api = Mock(spec=GitHub)
        api.api.side_effect = [{"incomplete_results": False, "total_count": 0, "items": []}, {}]
        with patch.dict(os.environ, environment, clear=True), patch("smoke_recovery.GitHub", return_value=api), patch.object(
            sys, "path", sys.path.copy()
        ):
            exec(code, {"__name__": "__main__"})
        return api

    def test_failed_fleet_notifies_owner_without_draft_or_main_green_claim(self):
        api = self.run_notification({"admit": "success", "stage": "success", "native": "failure", "publish": "skipped"},
                                    url="https://untrusted.invalid/stale-output")
        self.assertEqual(2, api.api.call_count)
        call = api.api.call_args
        self.assertEqual("repos/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/issues", call.args[0])
        body = call.kwargs["payload"]["body"]
        self.assertIn("@owner", body)
        self.assertIn("- propose: `success`", body)
        self.assertIn("- native: `failure`", body)
        self.assertIn("- publish: `skipped`", body)
        self.assertIn("No successfully published repair is claimed", body)
        self.assertNotIn("untrusted.invalid", body)
        self.assertNotIn("Verified repair draft", body)
        self.assertIn("cycle-100-1-iteration-1", call.kwargs["payload"]["title"])

    def test_success_notification_links_only_valid_draft_and_keeps_main_distinction(self):
        url = "https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/123"
        api = self.run_notification({name: "success" for name in ("admit", "stage", "native", "publish")}, url=url)
        body = api.api.call_args.kwargs["payload"]["body"]
        self.assertIn(f"[Verified repair draft]({url})", body)
        self.assertIn("does not make the original main run green", body)
        self.assertIn("A human must review and merge", body)
        self.assertIn("No automatic approval, merge, production write", body)

    def test_authenticated_feedback_on_first_two_iterations_reports_pending_automatic_revision(self):
        failed = {"admit": "success", "stage": "success", "native": "failure", "publish": "skipped"}
        for iteration in ("1", "2"):
            with self.subTest(iteration=iteration):
                api = self.run_notification(failed, iteration=iteration, feedback_artifact_id="123456")
                body = api.api.call_args.kwargs["payload"]["body"]
                self.assertIn("next bounded repair iteration", body)
                self.assertIn("no successful repair or green main is claimed", body)
                self.assertNotIn("Human investigation remains necessary", body)
                self.assertNotIn("Verified repair draft", body)

    def test_retry_progress_never_claimed_without_feedback_budget_and_successful_admission(self):
        failed = {"admit": "success", "stage": "success", "native": "failure", "publish": "skipped"}
        variants = [(failed, "3", "123456"), (failed, "1", ""), (failed, "1", "0"),
                    (failed, "1", "123\n456"), (failed, "1", "123;echo yes"),
                    (failed, "1", "1" * 20), ({**failed, "native": "cancelled"}, "1", "123456"),
                    ({**failed, "admit": "failure"}, "1", "123456"),
                    ({**failed, "stage": "failure"}, "1", "123456"),
                    ({**failed, "publish": "failure"}, "1", "123456")]
        for results, iteration, artifact_id in variants:
            with self.subTest(results=results, iteration=iteration, artifact_id=artifact_id):
                api = self.run_notification(results, iteration=iteration, feedback_artifact_id=artifact_id)
                body = api.api.call_args.kwargs["payload"]["body"]
                self.assertNotIn("next bounded repair iteration", body)
                self.assertIn("Human investigation remains necessary", body)

    def test_admission_failure_or_cancellation_still_produces_controller_fallback_report(self):
        for failed in ("failure", "cancelled", "skipped"):
            with self.subTest(failed=failed):
                api = self.run_notification({"admit": failed, "stage": "skipped", "native": "skipped", "publish": "skipped"},
                                            cycle_id="", iteration="")
                self.assertIn("controller-12345", api.api.call_args.kwargs["payload"]["title"])

    def test_report_rejects_invalid_identity_recipient_or_inconsistent_success(self):
        from orchestration_contract import ContractError
        failed = {"admit": "success", "stage": "success", "native": "failure", "publish": "skipped"}
        variants = [{"cycle_id": "100-1\n@someone", "iteration": "1"}, {"cycle_id": "100-1", "iteration": "4"},
                    {"cycle_id": "", "iteration": "1"}, {"recipient": "owner\n@everyone"}]
        for arguments in variants:
            with self.subTest(arguments=arguments), self.assertRaises(ContractError):
                self.run_notification(failed, **arguments)
        for results, url in (({**failed, "publish": "success"}, "https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/123"),
                             ({name: "success" for name in failed}, ""),
                             ({name: "success" for name in failed}, "https://untrusted.invalid/pull/123"),
                             ({**failed, "native": "in_progress"}, "")):
            with self.subTest(results=results, url=url), self.assertRaises(ContractError):
                self.run_notification(results, url=url)
        for needs in ({}, {"publish": {"result": "success"}}, [], {name: "failure" for name in failed}):
            with self.subTest(needs=needs), self.assertRaises(ContractError):
                self.run_notification(failed, raw_needs=needs)


if __name__ == "__main__":
    unittest.main()
