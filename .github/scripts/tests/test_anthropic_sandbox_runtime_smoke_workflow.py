"""Exercise the real inline contract shells; fixtures are not native Arm evidence."""

import copy
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[3]
SLUG = "anthropic-sandbox-runtime"
VERSION = "0.0.81"
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
                       NPM_LATEST_ENDPOINT="data:application/json,%7B%22version%22%3A%220.0.81%22%7D",
                       PACKAGE_NAME=SLUG, BASELINE_READY="failure::skipped",
                       PYTHONDONTWRITEBYTECODE="1")
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
            env.update(extra)
            process = subprocess.run(
                ["/bin/bash", "-e", "-o", "pipefail", "-c", self.steps[step_id]["run"]],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=15,
            )
            values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
            self.last_report = report.read_text() if report.exists() else ""
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

    def summarize(self, states, **extra):
        process, outputs = self.execute("test6", states, **extra)
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
        self.assertIn("|| 'not_installed'", self.job["outputs"]["package_version"])
        self.assertIn("|| 'failed'", self.job["outputs"]["regression_status"])
        self.assertIn("|| 'baseline_failed'", self.job["outputs"]["regression_decision"])
        self.assertIn("|| 'not_evaluated'", self.job["outputs"]["regression_latest_version"])
        self.assertIn(
            "dashboard_link=/linux/opensource_packages/anthropic-sandbox-runtime",
            self.steps["metadata"]["run"],
        )
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

    def test_passing_baseline_reports_current_is_latest(self):
        process, summary, regression = self.summarize(self.baseline())
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(summary["overall_status"], "success")
        self.assertEqual(summary["passed"], "5")
        self.assertEqual(summary["skipped"], "1")
        self.assertEqual(summary["duration"], "15")
        self.assertEqual(regression["decision"], "current_is_latest_stable")
        self.assertEqual(regression["status"], "skipped")
        self.assertEqual(regression["latest_version"], "0.0.81")
        self.assertEqual(regression["next_installed_version"], "not_installed")
        self.assertIn(
            "The tested baseline 0.0.81 matches the live npm latest tag.",
            self.last_report,
        )
        self.assertNotIn("that newer release was not installed", self.last_report)

    def test_new_npm_latest_is_reported_without_claiming_it_passed(self):
        endpoint = "data:application/json,%7B%22version%22%3A%220.0.82%22%7D"
        process, summary, outputs = self.summarize(
            self.baseline(), NPM_LATEST_ENDPOINT=endpoint
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(summary["overall_status"], "success")
        self.assertEqual(outputs["decision"], "upgrade_candidate_available")
        self.assertEqual(outputs["status"], "skipped")
        self.assertEqual(outputs["latest_version"], "0.0.82")
        self.assertEqual(outputs["next_installed_version"], "not_installed")
        self.assertIn(
            "The tested baseline 0.0.81 passed Tests 1-5. Live npm latest is "
            "0.0.82; that newer release was not installed or validated in this run.",
            self.last_report,
        )
        self.assertNotIn("matches the live npm latest tag", self.last_report)

    def test_latest_lookup_failure_fails_closed(self):
        process, outputs = self.execute(
            "test6", self.baseline(), NPM_LATEST_ENDPOINT="file:///does/not/exist"
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(outputs["decision"], "next_lookup_failed")
        self.assertEqual(outputs["status"], "failed")
        self.assertEqual(outputs["latest_version"], "not_checked")

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

    def test_functional_commands_and_locked_install_are_present(self):
        text = WORKFLOW.read_text()
        for marker in ["sha256sum -c -", "npm ci --prefix", "--ignore-scripts",
                       "sandbox-runtime-0.0.81.tgz", "Sandbox Runtime npm tarball SRI mismatch",
                       "sha512-bjHDu87gjIR7+Oxy9jPiK3v8CvSELCzfpXa3fjqfSKdvlZET2iF51xcXILWPayTpowB3xtZeQVf2JR916nVW/w==",
                       ".github/locks/anthropic-sandbox-runtime/package-lock.json",
                       "7259e88f71d668b12c2b04fbe465e767d0e023ad3a9b9c39bbed195601f99a5e",
                       "@pondwader/socks5-server/package.json",
                       "node-v22.21.1-linux-arm64.tar.xz", "--unshare-pid --unshare-user",
                       "FILESYSTEM_ENFORCEMENT_OK", "errno.EPERM", "error.code == 403",
                       "srt-apparmor-original"]:
            self.assertIn(marker, text)
        self.assertNotIn("npm install --prefix", text)
        self.assertNotIn("--help", "\n".join(self.steps[f"test{i}"]["run"] for i in range(1, 6)))
        page = ROOT / "content/linux/opensource_packages" / f"{SLUG}.md"
        frontmatter = yaml.safe_load(page.read_text().split("---", 2)[1])
        self.assertIs(frontmatter["draft"], False)
        self.assertEqual(frontmatter["supported_minimum_version"]["version_number"], "0.0.1")
        self.assertEqual(frontmatter["supported_minimum_version"]["release_date"], "2025/10/20")
        self.assertIn("40567951981/job/122414153746", page.read_text())
        self.assertEqual(frontmatter["category"], "Identity & Security")
        self.assertIn("npmjs.com/package/@anthropic-ai/sandbox-runtime", frontmatter["download_url"])
        self.assertIn("registry.npmjs.org/@anthropic-ai%2Fsandbox-runtime/latest", text)

    def test_npm_sri_gate_rejects_corruption_before_install(self):
        install = self.steps["install"]["run"]
        self.assertLess(install.index("npm tarball SRI mismatch"), install.index("npm ci --prefix"))
        self.assertNotIn("bun-v", install)
        self.assertNotIn("npm run build", install)
        gate = install.split("python3 - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
        with tempfile.TemporaryDirectory(prefix="srt-sri-negative-") as temporary:
            tools = Path(temporary) / "srt-tools"
            tools.mkdir()
            (tools / "sandbox-runtime-0.0.81.tgz").write_bytes(b"corrupted npm artifact")
            process = subprocess.run([sys.executable, "-c", gate], text=True,
                                     capture_output=True,
                                     env=dict(os.environ, RUNNER_TEMP=temporary))
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("npm tarball SRI mismatch", process.stderr)

    def test_dependency_lock_pins_exact_versions_and_integrities(self):
        lock_path = ROOT / ".github/locks/anthropic-sandbox-runtime/package-lock.json"
        lock = json.loads(lock_path.read_text())
        self.assertEqual(lock["lockfileVersion"], 3)
        expected = {
            "node_modules/@anthropic-ai/sandbox-runtime": "0.0.81",
            "node_modules/@pondwader/socks5-server": "1.0.10",
            "node_modules/commander": "12.1.0",
            "node_modules/node-forge": "1.4.2",
            "node_modules/zod": "3.25.76",
        }
        self.assertEqual(set(lock["packages"]), {"", *expected})
        for package, version in expected.items():
            with self.subTest(package=package):
                record = lock["packages"][package]
                self.assertEqual(record["version"], version)
                self.assertRegex(record["integrity"], r"^sha512-[A-Za-z0-9+/]+={0,2}$")

    def test_general_linux_requirements_are_not_public_arm_caveats(self):
        page = ROOT / "content/linux/opensource_packages" / f"{SLUG}.md"
        metadata = yaml.safe_load(page.read_text().split("---", 2)[1])
        self.assertIsNone(metadata["optional_info"]["support_caveats"])
        self.assertNotIn("support_caveats_inline", metadata["optional_info"])
        hidden = metadata["optional_hidden_info"]["other_info"]
        self.assertIn("Linux use requires", hidden)
        self.assertIn("tested compatibility floor", hidden)
        self.assertEqual(
            metadata["optional_hidden_info"]["release_notes__supported_minimum"],
            "https://www.npmjs.com/package/@anthropic-ai/sandbox-runtime/v/0.0.1",
        )
        self.assertTrue(
            metadata["optional_info"]["getting_started_resources"]["official_docs"].endswith(
                "README.md#unix-socket-restrictions-linux"
            )
        )

    def filesystem_probe(self, write_errno):
        script = self.steps["test4"]["run"]
        probe = script.split("-- python3 -c '\n", 1)[1].split("\n' \"$SRT_FIXTURE\"", 1)[0]
        with tempfile.TemporaryDirectory(prefix="srt-filesystem-fixture-") as temporary:
            root = Path(temporary)
            (root / "secret").write_text("private fixture")
            (root / "protected").write_text("unchanged")
            original_open = Path.open

            def restricted_open(path, mode="r", *args, **kwargs):
                if path == root / "secret" and mode == "r":
                    raise PermissionError(errno.EACCES, "fixture denied read")
                if path == root / "protected" and mode == "w" and write_errno is not None:
                    raise OSError(write_errno, "fixture write result")
                return original_open(path, mode, *args, **kwargs)

            with mock.patch.object(Path, "open", restricted_open), \
                    mock.patch.object(sys, "argv", ["probe", str(root)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                exec(compile(probe, "<actual-workflow-filesystem-probe>", "exec"), {})

    def test_readonly_mount_is_a_valid_write_denial(self):
        self.filesystem_probe(errno.EROFS)

    def test_write_bypass_and_unexpected_io_error_fail_the_actual_probe(self):
        for result in (None, errno.ENOSPC, errno.ENOENT):
            with self.subTest(result=result), self.assertRaises(AssertionError):
                self.filesystem_probe(result)


if __name__ == "__main__":
    unittest.main()
