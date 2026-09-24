from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exact_run_aggregation import _yaml_mapping
from ci_change_scope import classify_paths

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github/workflows"


def workflow(name):
    return _yaml_mapping((WORKFLOWS / name).read_bytes(), name)


class RepairWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.parent = workflow("test-all-packages-orchestrator.yml")
        self.repair = workflow("smoke-repair.yml")
        self.package = workflow("smoke-repair-package.yml")
        self.receiver = workflow("smoke-repair-receive.yml")

    def test_new_workflows_are_internal_only_and_disabled_by_default(self):
        for document in (self.repair, self.package):
            self.assertEqual(set(document["on"]), {"workflow_call"})
            self.assertNotIn("secrets", document["on"]["workflow_call"])
        caller = self.parent["jobs"]["repair"]
        self.assertEqual(caller["uses"], "./.github/workflows/smoke-repair.yml")
        for guard in ("always()", "vars.SMOKE_REPAIR_ENABLED == 'true'",
                      "needs.orchestrate-batches.result == 'failure'",
                      "needs.scope.outputs.smoke == 'true'"):
            self.assertIn(guard, caller["if"])
        self.assertIn("outputs.evidence_artifact_id != ''", caller["if"])
        for document, job in ((self.repair, "prepare"), (self.package, "propose")):
            self.assertIn("github.ref == 'refs/heads/main'", document["jobs"][job]["if"])
            self.assertIn("vars.SMOKE_REPAIR_ENABLED == 'true'", document["jobs"][job]["if"])

    def test_exact_parent_attempt_and_artifact_are_passed(self):
        caller = self.parent["jobs"]["repair"]["with"]
        self.assertEqual(caller["base_sha"], "${{ github.sha }}")
        self.assertEqual(caller["orchestrator_run_id"], "${{ github.run_id }}")
        self.assertIn("needs.orchestrate-batches.outputs.run_attempt", caller["orchestrator_attempt"])
        self.assertEqual(caller["evidence_artifact_id"], "${{ needs.orchestrate-batches.outputs.evidence_artifact_id }}")
        job = self.parent["jobs"]["orchestrate-batches"]
        self.assertEqual(job["outputs"]["evidence_artifact_id"], "${{ steps.evidence.outputs.artifact-id }}")
        upload = next(step for step in job["steps"] if step.get("id") == "evidence")
        self.assertEqual(upload["if"], "always()")

    def test_request_callback_serialization_and_job_dependencies(self):
        self.assertNotIn("repair", self.repair["jobs"])
        self.assertEqual(self.receiver["on"], {"repository_dispatch": {"types": ["smoke-repair-proposal"]}})
        self.assertEqual(self.receiver["concurrency"], {
            "group": "smoke-repair-publication", "cancel-in-progress": False, "queue": "max"})
        caller = self.receiver["jobs"]["repair"]
        self.assertEqual(caller["needs"], "receive")
        self.assertEqual(caller["uses"], "./.github/workflows/smoke-repair-package.yml")
        self.assertEqual(caller["with"], {
            "base_sha": "${{ needs.receive.outputs.base_sha }}",
            "package_slug": "${{ needs.receive.outputs.package_slug }}",
            "proposal_artifact_id": "${{ needs.receive.outputs.artifact_id }}",
        })
        jobs = self.package["jobs"]
        self.assertEqual(jobs["stage"]["needs"], "propose")
        self.assertEqual(jobs["native"]["needs"], "stage")
        self.assertEqual(jobs["publish"]["needs"], ["propose", "stage", "native"])
        self.assertEqual(jobs["report"]["needs"], ["propose", "stage", "native", "publish"])
        self.assertEqual(jobs["report"]["if"], "always()")
        for document in (self.repair, self.package, self.receiver):
            for job in document["jobs"].values():
                self.assertIs(job.get("continue-on-error", False), False)

    def test_monitor_is_serialized_gated_and_uses_only_trusted_main(self):
        flow = workflow("smoke-recovery-monitor.yml")
        self.assertEqual(set(flow["on"]), {"workflow_run", "schedule", "workflow_dispatch"})
        self.assertEqual(flow["on"]["workflow_run"], {
            "workflows": ["Test All Packages (Orchestrator) on Arm64"], "types": ["completed"], "branches": ["main"]})
        self.assertEqual(flow["concurrency"], {
            "group": "smoke-recovery-incident", "cancel-in-progress": False, "queue": "max"})
        job = flow["jobs"]["monitor"]
        self.assertIn("vars.SMOKE_RECOVERY_MONITOR_ENABLED == 'true'", job["if"])
        self.assertEqual(job["runs-on"], "ubuntu-24.04-arm")
        self.assertEqual(job["permissions"], {"contents": "read", "actions": "read", "pull-requests": "read", "issues": "write"})
        checkout = job["steps"][0]["with"]
        self.assertEqual(checkout["ref"], "${{ github.sha }}")
        self.assertEqual(checkout["fetch-depth"], 0)
        self.assertIs(checkout["persist-credentials"], False)
        self.assertNotIn("github.event.workflow_run.head_sha", str(job))
        self.assertNotIn("secrets.", str(job))
        self.assertNotIn("download-artifact", str(job))
        self.assertIn("smoke_recovery_incident.py watch", job["steps"][-1]["run"])
        self.assertEqual(job["steps"][-1]["env"]["SMOKE_NOTIFICATION_LOGIN"],
                         "${{ vars.SMOKE_NOTIFICATION_LOGIN }}")

    def test_only_free_arm_and_reviewed_checkout_with_no_persisted_token(self):
        for document in (self.repair, self.package, self.receiver):
            for job in document["jobs"].values():
                if "steps" not in job:
                    continue
                self.assertEqual(job["runs-on"], "ubuntu-24.04-arm")
                self.assertLessEqual(job["timeout-minutes"], 65)
                for step in job["steps"]:
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"^[A-Za-z0-9_/-]+@[0-9a-f]{40}$")
                    if step.get("uses", "").startswith("actions/checkout@"):
                        self.assertEqual(step["with"]["ref"], "${{ github.sha }}")
                        self.assertIs(step["with"]["persist-credentials"], False)
                    self.assertNotIn("secrets: inherit", str(step))

    def test_credentials_are_separated_from_model_and_native_executor(self):
        jobs = self.package["jobs"]
        self.assertNotIn("environment", jobs["propose"])
        self.assertEqual(jobs["propose"]["permissions"], {"contents": "read", "actions": "read"})
        self.assertEqual(jobs["native"]["permissions"], {"contents": "read", "actions": "write"})
        self.assertNotIn("environment", jobs["native"])
        self.assertNotIn("secrets.", str(jobs["native"]))
        self.assertNotIn("SMOKE_REPAIR_OPENAI_API_KEY", str(jobs["stage"]))
        self.assertNotIn("SMOKE_REPAIR_OPENAI_API_KEY", str(jobs["publish"]))
        for name in ("stage", "publish"):
            job = jobs[name]
            self.assertEqual(job["environment"], "smoke-repair-delivery")
            self.assertEqual(job["permissions"], {"contents": "read", "actions": "read"})
            steps = job["steps"]
            minted = next(index for index, step in enumerate(steps) if step.get("id") == "repair_token")
            before = "\n".join(step.get("run", "") for step in steps[:minted])
            self.assertIn("smoke_repair_pipeline.py admit", before)
            self.assertIn("smoke_repair_pipeline.py current", before)
            if name == "publish":
                self.assertIn("smoke_repair_native.py --mode verify", before)
            else:
                self.assertIn("smoke_repair_publisher.py admit", before)
            self.assertEqual({key: value for key, value in steps[minted]["with"].items() if key.startswith("permission-")},
                             {"permission-contents": "write", "permission-pull-requests": "write",
                              "permission-workflows": "write", "permission-actions": "read"})
            self.assertNotIn("DASHBOARD_DELIVERY_APP_PRIVATE_KEY", str(job))

    def test_public_receiver_has_no_model_access_and_rechecks_admission(self):
        job = self.package["jobs"]["propose"]
        steps = job["steps"]
        guard = next(step for step in steps if step.get("name") == "Recheck proposal against the exact reviewed source")
        self.assertIn("smoke_repair_pipeline.py receive", guard["run"])
        self.assertIn('[[ "$BASE_SHA" == "$GITHUB_SHA" ]]', guard["run"])
        for argument in ("context", "proposal", "slug", "repository", "base-sha", "source-output", "contract-output"):
            self.assertIn("--" + argument, guard["run"])
        self.assertNotIn("secrets.", str(job))
        self.assertNotIn("SMOKE_REPAIR_OPENAI_API_KEY", str(job))
        self.assertNotIn("openai", str(job).lower())
        self.assertNotIn("smoke_repair_model.py", str(job))
        upload = next(step for step in steps if step.get("id") == "upload")
        self.assertLess(steps.index(guard), steps.index(upload))
        self.assertNotIn("if", upload)
        self.assertNotIn("if", self.package["jobs"]["stage"])
        receiver = self.receiver["jobs"]["receive"]
        self.assertEqual(receiver["permissions"], {"contents": "read", "actions": "read"})
        self.assertNotIn("environment", receiver)
        self.assertNotIn("secrets.", str(receiver))
        self.assertIn("vars.SMOKE_REPAIR_ENABLED == 'true'", receiver["if"])
        self.assertIn("github.actor == vars.SMOKE_REPAIR_BRIDGE_BOT_LOGIN", receiver["if"])
        admission = next(step for step in receiver["steps"] if step.get("id") == "admit")
        self.assertIn('smoke_repair_bridge.py', admission["run"])
        self.assertIn('--event "$GITHUB_EVENT_PATH"', admission["run"])
        self.assertNotIn("github.event.client_payload", str(receiver))
        self.assertEqual(admission["env"]["SMOKE_REPAIR_BRIDGE_BOT_ID"], "${{ vars.SMOKE_REPAIR_BRIDGE_BOT_ID }}")

    def test_all_downloads_use_exact_artifact_ids_and_uploads_are_required(self):
        for document in (self.repair, self.package, self.receiver):
            for job in document["jobs"].values():
                for step in job.get("steps", []):
                    if step.get("uses", "").startswith("actions/download-artifact@"):
                        self.assertIn("artifact-ids", step["with"])
                        self.assertNotIn("name", step["with"])
                        self.assertNotIn("pattern", step["with"])
                    if step.get("uses", "").startswith("actions/upload-artifact@"):
                        self.assertEqual(step["with"]["if-no-files-found"], "error")
                        self.assertIn("github.run_attempt", step["with"]["name"])

    def test_catalog_validation_uses_exact_base_and_pinned_hugo_before_write_token(self):
        steps = self.package["jobs"]["stage"]["steps"]
        validation = next(step for step in steps if step.get("name") == "Validate exact reviewed catalog before delivery credentials")
        mint = next(step for step in steps if step.get("id") == "repair_token")
        self.assertLess(steps.index(validation), steps.index(mint))
        self.assertNotIn("if", validation)
        self.assertNotIn("continue-on-error", validation)
        self.assertNotIn("secrets.", str(validation))
        self.assertEqual(validation["env"], {
            "REVIEWED_BASE_SHA": "${{ github.sha }}", "HUGO_VERSION": "0.130.0",
            "HUGO_ARM64_ARCHIVE_SHA256": "025785b56d6217d2528ad8782680332851acae0d78cc9f86a27f8e03ec1afa3c",
        })
        for command in ("set -euo pipefail", "sha256sum --check --strict",
                        'test "$(git rev-parse HEAD)" = "$REVIEWED_BASE_SHA"',
                        "python3 -I -B build_steps/validate_package_identity_catalog.py",
                        '--revision "$REVIEWED_BASE_SHA" --hugo-binary "$install_dir/hugo"'):
            self.assertIn(command, validation["run"])

    def test_owner_report_waits_for_repair_and_preserves_failed_outcome(self):
        notify = self.parent["jobs"]["notify"]
        self.assertIn("repair", notify["needs"])
        step = next(step for step in notify["steps"] if step.get("name") == "Notify the smoke-run owner")
        self.assertEqual(step["env"]["REPAIR_OUTCOME"], "${{ needs.repair.result }}")
        self.assertIn('--repair-outcome "$REPAIR_OUTCOME"', step["run"])
        report = self.package["jobs"]["report"]
        self.assertEqual(report["permissions"], {"contents": "read", "issues": "write"})
        step = report["steps"][-1]
        self.assertEqual(step["env"]["SMOKE_REPAIR_PR_URL"], "${{ needs.publish.outputs.pull_request_url }}")

    def test_repair_code_and_tests_are_smoke_scope_without_dashboard_deployment(self):
        paths = [str(path.relative_to(ROOT)) for path in (ROOT / ".github/scripts").glob("smoke_repair_*.py")]
        paths += [str(path.relative_to(ROOT)) for path in (ROOT / ".github/scripts/tests").glob("test_smoke_repair_*.py")]
        paths += [".github/workflows/smoke-repair.yml", ".github/workflows/smoke-repair-package.yml"]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(classify_paths([path]), {"smoke": True, "dashboard": False})
        foundation = (WORKFLOWS / "exact-run-aggregation-foundation-ci.yml").read_text()
        for path in ("'.github/scripts/smoke_repair_*.py'", "'.github/scripts/tests/test_smoke_repair_*.py'",
                     "'.github/workflows/smoke-repair*.yml'"):
            self.assertIn(path, foundation)
        lint = next(step["run"] for step in workflow("exact-run-aggregation-foundation-ci.yml")["jobs"]["exact-run-contract"]["steps"]
                    if step.get("name") == "Lint foundation workflow")
        self.assertIn(".github/workflows/smoke-repair.yml", lint)
        self.assertIn(".github/workflows/smoke-repair-package.yml", lint)


if __name__ == "__main__":
    unittest.main()
