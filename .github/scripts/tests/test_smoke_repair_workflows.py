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

    def test_matrix_limits_and_job_dependencies(self):
        matrix = self.repair["jobs"]["repair"]
        self.assertEqual(matrix["strategy"]["max-parallel"], 2)
        self.assertIs(matrix["strategy"]["fail-fast"], False)
        self.assertEqual(matrix["strategy"]["matrix"], "${{ fromJSON(needs.prepare.outputs.matrix) }}")
        jobs = self.package["jobs"]
        self.assertEqual(jobs["stage"]["needs"], "propose")
        self.assertEqual(jobs["native"]["needs"], "stage")
        self.assertEqual(jobs["publish"]["needs"], ["propose", "stage", "native"])
        self.assertEqual(jobs["report"]["needs"], ["propose", "stage", "native", "publish"])
        self.assertEqual(jobs["report"]["if"], "always()")
        for document in (self.repair, self.package):
            for job in document["jobs"].values():
                self.assertIs(job.get("continue-on-error", False), False)

    def test_only_free_arm_and_reviewed_checkout_with_no_persisted_token(self):
        for document in (self.repair, self.package):
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
        self.assertEqual(jobs["propose"]["environment"], "smoke-repair-analysis")
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
            if name == "publish":
                self.assertIn("smoke_repair_native.py --mode verify", before)
            else:
                self.assertIn("smoke_repair_publisher.py admit", before)
            self.assertEqual({key: value for key, value in steps[minted]["with"].items() if key.startswith("permission-")},
                             {"permission-contents": "write", "permission-pull-requests": "write",
                              "permission-workflows": "write", "permission-actions": "read"})
            self.assertNotIn("DASHBOARD_DELIVERY_APP_PRIVATE_KEY", str(job))

    def test_all_downloads_use_exact_artifact_ids_and_uploads_are_required(self):
        for document in (self.repair, self.package):
            for job in document["jobs"].values():
                for step in job.get("steps", []):
                    if step.get("uses", "").startswith("actions/download-artifact@"):
                        self.assertIn("artifact-ids", step["with"])
                        self.assertNotIn("name", step["with"])
                        self.assertNotIn("pattern", step["with"])
                    if step.get("uses", "").startswith("actions/upload-artifact@"):
                        self.assertEqual(step["with"]["if-no-files-found"], "error")
                        self.assertIn("github.run_attempt", step["with"]["name"])

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
