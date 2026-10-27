"""Exercise the real inline contract shells; fixtures are not native Arm evidence."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
SLUG = "openshell"
VERSION = "0.1.6"
WORKFLOW = ROOT / ".github/workflows" / f"test-{SLUG}.yml"
EXPECTED_OUTPUTS = ["contract_version","package_slug","package_name","package_version","run_status","badge_status","core_failed","tests_passed","tests_failed","tests_skipped","duration_seconds","regression_status","regression_decision","regression_result","regression_comparison","regression_current_version","regression_latest_version","regression_next_installed_version","regression_applicability","run_id","run_attempt","job_name","dashboard_link","timestamp"]


class SmokeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = yaml.safe_load(WORKFLOW.read_text())
        cls.job = cls.document["jobs"][f"test-{SLUG}"]
        cls.steps = {step["id"]: step for step in cls.job["steps"] if "id" in step}

    def execute(self, step_id, states=None, **extra):
        with tempfile.TemporaryDirectory(prefix=f"{SLUG}-contract-") as temporary:
            output = Path(temporary) / "output"
            report = Path(temporary) / "report"
            env = dict(os.environ, GITHUB_OUTPUT=str(output),
                       GITHUB_STEP_SUMMARY=str(report), RUNNER_TEMP=temporary,
                       STEPS_JSON=json.dumps(states or {}),
                       PACKAGE_NAME=SLUG, BASELINE_READY="failure::skipped",
                       PYTHONDONTWRITEBYTECODE="1")
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
            env.update(extra)
            process = subprocess.run(
                ["/bin/bash", "-e", "-o", "pipefail", "-c", self.steps[step_id]["run"]],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=15,
            )
            values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
            return process, values

    def baseline(self):
        states = {
            "metadata": {"outcome": "success", "outputs": {}},
            "install": {"outcome": "success", "outputs": {"install_status": "success"}},
            "version": {"outcome": "success", "outputs": {"version": VERSION}},
            "cleanup": {"outcome": "success", "outputs": {}},
        }
        for ordinal in range(1, 6):
            states[f"test{ordinal}"] = {
                "outcome": "success", "outputs": {"status": "passed", "duration": str(ordinal)}}
        return states

    def summarize(self, states):
        process, outputs = self.execute("test6", states)
        self.assertEqual(process.returncode, 0, process.stderr)
        states = copy.deepcopy(states)
        states["test6"] = {"outcome": "success", "outputs": outputs}
        process, summary = self.execute("summary", states)
        return process, summary, outputs

    def test_contract_and_checkout(self):
        triggers = self.document.get("on", self.document.get(True))
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual(set(triggers["workflow_call"]["outputs"]), set(EXPECTED_OUTPUTS))
        self.assertEqual(set(self.job["outputs"]), set(EXPECTED_OUTPUTS))
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        self.assertEqual(self.document["permissions"], {"contents": "read"})
        actions = [step for step in self.job["steps"] if "uses" in step]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["uses"], "actions/checkout@11d5960a326750d5838078e36cf38b85af677262")
        self.assertIs(actions[0]["with"]["persist-credentials"], False)
        self.assertNotIn("'unknown'", WORKFLOW.read_text())
        self.assertIn("validate_six_test_result", self.steps["summary"]["run"])
        self.assertIn("|| 'baseline_failed'", self.job["outputs"]["regression_decision"])
        for ordinal in range(1, 6):
            step = self.steps[f"test{ordinal}"]
            self.assertIs(step["continue-on-error"], True)
            self.assertEqual(step["if"], "always()")
            self.assertIn('trap finish_test EXIT', step["run"])

    def test_all_shells_parse(self):
        for step in self.job["steps"]:
            if "run" in step:
                process = subprocess.run(["/bin/bash", "-n"], input=step["run"],
                                         text=True, capture_output=True)
                self.assertEqual(process.returncode, 0, process.stderr)

    def test_missing_install_fails_every_mandatory_test_with_outputs(self):
        for ordinal in range(1, 6):
            with self.subTest(test=ordinal):
                process, outputs = self.execute(f"test{ordinal}")
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(outputs.get("status"), "failed")
                self.assertTrue(outputs.get("duration", "").isdigit())

    def test_passing_baseline_explicitly_defers_regression(self):
        process, summary, regression = self.summarize(self.baseline())
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(summary["overall_status"], "success")
        self.assertEqual(summary["passed"], "5")
        self.assertEqual(summary["skipped"], "1")
        self.assertEqual(summary["duration"], "15")
        self.assertEqual(regression["decision"], "runtime_validation_not_automated")
        self.assertEqual(regression["status"], "skipped")
        self.assertEqual(regression["latest_version"], "not_evaluated")
        self.assertEqual(regression["next_installed_version"], "not_installed")

    def test_each_failed_outcome_overrides_a_pass_output(self):
        for ordinal in range(1, 6):
            states = self.baseline()
            states[f"test{ordinal}"]["outcome"] = "failure"
            process, summary, regression = self.summarize(states)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(summary["badge_status"], "failing")
            self.assertEqual(summary["core_failed"], "1")
            self.assertEqual(regression["decision"], "baseline_failed")

    def test_missing_and_skipped_core_evidence_fail_closed(self):
        for outcome in ("skipped", "cancelled", ""):
            states = self.baseline()
            states["test5"]["outcome"] = outcome
            process, summary, unused = self.summarize(states)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(summary["core_failed"], "1")
        states = self.baseline()
        del states["test5"]
        self.assertNotEqual(self.summarize(states)[0].returncode, 0)

    def test_missing_version_or_install_marker_cannot_pass(self):
        for step, key in (("version", "version"), ("install", "install_status")):
            states = self.baseline()
            states[step]["outputs"].pop(key)
            # Real core steps reject incomplete install/version evidence first.
            states["test1"]["outcome"] = "failure"
            process, summary, regression = self.summarize(states)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(summary["overall_status"], "failure")
            self.assertEqual(regression["decision"], "baseline_install_failed")

    def test_impossible_passing_core_with_missing_version_is_rejected(self):
        states = self.baseline()
        states["version"]["outputs"].clear()
        process, outputs = self.execute("test6", states)
        self.assertNotEqual(process.returncode, 0)
        states["test6"] = {"outcome": "failure", "outputs": outputs}
        process, summary = self.execute("summary", states)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(summary["overall_status"], "failure")

    def test_cleanup_failure_cannot_publish_passing_result(self):
        states = self.baseline()
        states["cleanup"]["outcome"] = "failure"
        process, summary, unused = self.summarize(states)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(summary["overall_status"], "failure")

    def test_invalid_duration_or_test6_evidence_fails_closed(self):
        for value in ("", "-1", "NaN"):
            states = self.baseline()
            states["test1"]["outputs"]["duration"] = value
            self.assertNotEqual(self.summarize(states)[0].returncode, 0)
        states = self.baseline()
        process, outputs = self.execute("test6", states)
        self.assertEqual(process.returncode, 0)
        for mutation in ("failure", "unapproved_decision"):
            broken = copy.deepcopy(states)
            broken["test6"] = {"outcome": "success", "outputs": copy.deepcopy(outputs)}
            if mutation == "failure":
                broken["test6"]["outcome"] = "failure"
            else:
                broken["test6"]["outputs"]["decision"] = mutation
            process, summary = self.execute("summary", broken)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(summary["overall_status"], "failure")

    def test_functional_commands_and_immutable_install_are_present(self):
        text = WORKFLOW.read_text()
        for marker in ["sha256sum -c -","openshell sandbox create","--policy","openshell sandbox exec","FILESYSTEM_ENFORCEMENT_OK","openshell sandbox delete","docker run --rm --network none","https://127.0.0.1:17670 --local --name openshell"]:
            self.assertIn(marker, text)
        self.assertNotIn("--help", "\n".join(self.steps[f"test{i}"]["run"] for i in range(1, 6)))
        page = ROOT / "content/linux/opensource_packages" / f"{SLUG}.md"
        frontmatter = yaml.safe_load(page.read_text().split("---", 2)[1])
        self.assertIs(frontmatter["draft"], False)
        self.assertEqual(frontmatter["supported_minimum_version"]["version_number"], "0.0.6")
        self.assertEqual(frontmatter["supported_minimum_version"]["release_date"], "2026/03/16")
        self.assertIn("gtc26-s81765", page.read_text())
        self.assertIn("v0.0.6/docs/reference/support-matrix.md", page.read_text())
        self.assertEqual(frontmatter["category"], "Identity & Security")

    def test_public_caveat_is_concise_and_product_facing(self):
        page = ROOT / "content/linux/opensource_packages" / f"{SLUG}.md"
        metadata = yaml.safe_load(page.read_text().split("---", 2)[1])
        caveat = metadata["optional_info"]["support_caveats"]
        self.assertLessEqual(len(caveat), 550)
        for internal in ("workflow", "smoke", "regression", "synthetic"):
            self.assertNotIn(internal, caveat.lower())

    def test_sandbox_name_fits_upstream_limit_for_long_run_ids(self):
        script = self.steps["test3"]["run"]
        naming = next(line for line in script.splitlines() if line.startswith("SANDBOX="))
        for run_id, attempt in (("40567951981", "1"), ("9" * 20, "123456789")):
            process = subprocess.run(
                ["/bin/bash", "-c", naming + '\nprintf "%s" "$SANDBOX"'],
                text=True, capture_output=True, check=True,
                env=dict(os.environ, GITHUB_RUN_ID=run_id, GITHUB_RUN_ATTEMPT=attempt))
            self.assertLessEqual(len(process.stdout), 19)
            self.assertRegex(process.stdout, r"^arm-[a-f0-9]{12}$")
        self.assertIn('test "${#SANDBOX}" -le 19', script)

    def test_immutable_image_refs_and_architecture_gate(self):
        expected = {
            "OPENSHELL_SANDBOX_IMAGE": "ghcr.io/nvidia/openshell/sandbox@sha256:1038eb5c1f191fa3c34684fd7041b891c78ec570979d487f36e06e08f91bfb63",
            "OPENSHELL_SUPERVISOR_IMAGE": "ghcr.io/nvidia/openshell/supervisor@sha256:ce859a7d77ee515d3fe0b3c7dc61286516f402eb1d25c761d806d9ae5ed96c0b",
            "OPENSHELL_WORKLOAD_IMAGE": "nvcr.io/nvidia/base/ubuntu@sha256:d9461f428eea54e553add3a5158a0f245c6e1ea73efc59fff8e98e3d4a38e378",
        }
        for key, reference in expected.items():
            self.assertEqual(self.job["env"][key], reference)
        self.assertIn('IMAGE="$OPENSHELL_WORKLOAD_IMAGE"', self.steps["test5"]["run"])
        script = self.steps["test2"]["run"]
        gate = script[script.index("for image in "):script.index("\npython3 -")]
        with tempfile.TemporaryDirectory(prefix="openshell-image-fixture-") as temporary:
            tools = Path(temporary)
            (tools / "docker").write_text('#!/bin/sh\ncase "$1" in pull) exit 0;; image) printf "%s" "$FIXTURE_ARCH";; *) exit 90;; esac\n')
            (tools / "timeout").write_text('#!/bin/sh\nshift\nexec "$@"\n')
            for tool in tools.iterdir():
                tool.chmod(0o755)
            env = dict(os.environ, **expected, PATH=temporary + os.pathsep + os.environ["PATH"])
            for arch in ("arm64", "amd64", ""):
                process = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", gate],
                                         env=dict(env, FIXTURE_ARCH=arch), text=True, capture_output=True)
                self.assertEqual(process.returncode == 0, arch == "arm64", process.stderr)
            env["OPENSHELL_WORKLOAD_IMAGE"] = "nvcr.io/nvidia/base/ubuntu:24.04"
            process = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", gate],
                                     env=dict(env, FIXTURE_ARCH="arm64"), text=True, capture_output=True)
            self.assertNotEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
