"""Exercise the actual gem5 workflow scripts and reject hidden failures."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-gem5.yml"


class Gem5WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="gem5-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-gem5"]
        self.steps = {step.get("id", step["name"]): step for step in self.job["steps"]}
        self.env = dict(os.environ, **self.job["env"])
        self.env.update(GITHUB_OUTPUT=str(self.root / "output"), RUNNER_TEMP=str(self.root))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.tool("timeout", 'case "$1" in --kill-after=*) shift;; esac\nshift\nexec "$@"\n')
        self.tool("sudo", 'exec "$@"\n')
        self.env["DOCKER_CALLS"] = str(self.root / "docker-calls")
        self.env["FAKE_SOURCE"] = str(self.root / "baseline-src")
        self.tool("docker", '''printf 'CALL %s\\n' "$1" >> "$DOCKER_CALLS"
printf '%s\\n' "$@" >> "$DOCKER_CALLS"
case "$1" in
  pull) exit "${PULL_FAIL:-0}";;
  rm) exit 0;;
  run)
    if [ "${RUN_FAIL:-0}" -ne 0 ]; then exit "$RUN_FAIL"; fi
    export CC=gcc-10 CXX=g++-10
    cd "$FAKE_SOURCE" || exit 1
    exec bash -euo pipefail -c "$GEM5_SMOKE";;
  *) exit 99;;
esac
''')
        self.values = {}
        for number in range(1, 7):
            self.values[f"steps.test{number}.outputs.status"] = "passed"
            self.values[f"steps.test{number}.outcome"] = "success"
            self.values[f"steps.test{number}.outputs.duration"] = str(number)
        self.values.update({
            "steps.install.outputs.install_mode": "github_source",
            "steps.install.outputs.install_status": "success",
            "steps.version.outputs.version": self.env["BASELINE_VERSION"],
        })

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    def render(self, script):
        def replace(match):
            for term in match.group(1).split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term[1:-1]
                value = self.values.get(term)
                if value:
                    return value
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, script)

    def run_step(self, name, **env):
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.render(self.steps[name]["run"])],
            cwd=self.root, env=dict(self.env, **env), capture_output=True, text=True, timeout=15,
        )
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def test_summary_all_checks_pass_and_durations_are_counted(self):
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", outputs["passed"])
        self.assertEqual("21", outputs["duration"])
        self.assertEqual("0", outputs["failed"])

    def test_every_core_requires_status_and_successful_actual_outcome(self):
        for number in range(1, 6):
            for status, outcome in (("", "success"), ("skipped", "success"),
                                    ("failed", "success"), ("unknown", "success"),
                                    ("passed", ""), ("passed", "failure"),
                                    ("passed", "cancelled"), ("passed", "skipped")):
                with self.subTest(number=number, status=status, outcome=outcome):
                    self.values[f"steps.test{number}.outputs.status"] = status
                    self.values[f"steps.test{number}.outcome"] = outcome
                    result, outputs = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("1", outputs["core_failed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual("0", outputs["skipped"])
                    self.assertEqual("failure", outputs["overall_status"])
                    self.assertEqual("failing", outputs["badge_status"])
                self.values[f"steps.test{number}.outputs.status"] = "passed"
                self.values[f"steps.test{number}.outcome"] = "success"

    def test_all_missing_results_fail_closed(self):
        self.values.clear()
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("0", "6", "0", "5"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped", "core_failed")))

    def test_regression_skip_requires_success_and_exact_applicability(self):
        self.values["steps.test6.outputs.status"] = "skipped"
        self.values["steps.test6.outputs.decision"] = "no_newer_stable_available"
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped")))
        for decision, outcome in (("", "success"), ("runtime_validation_not_automated", "success"),
                                  ("not_configured", "success"), ("no_newer_stable_available", "failure"),
                                  ("no_newer_stable_available", "skipped"), ("no_newer_stable_available", "")):
            with self.subTest(decision=decision, outcome=outcome):
                self.values["steps.test6.outputs.decision"] = decision
                self.values["steps.test6.outcome"] = outcome
                result, outputs = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("0", outputs["core_failed"])

    def test_regression_failed_outcome_overrides_passed_output(self):
        self.values["steps.test6.outcome"] = "failure"
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("1", outputs["failed"])


    def test_missing_or_unresolved_baseline_tag_cannot_pass_install(self):
        self.tool("git", 'case "$1" in ls-remote) exit "${TAG_FAILURE:-0}";; *) exit 99;; esac\n')
        for failure in ("0", "1"):
            result, outputs = self.run_step("install", TAG_FAILURE=failure)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["install_status"])

    def test_dashboard_readme_does_not_expand_upstream_pattern(self):
        (self.root / "README.md").write_text("dashboard")
        (self.root / "baseline-src").mkdir()
        (self.root / "baseline-src/README").write_text("gem5 source documentation")
        result, outputs = self.run_step("test3")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])

    def test_logged_failure_and_missing_build_are_two_core_failures(self):
        self.values["steps.test3.outputs.status"] = "failed"
        self.values["steps.test3.outcome"] = "failure"
        self.values["steps.test5.outputs.status"] = ""
        self.values["steps.test5.outcome"] = "failure"
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("4", "2", "0", "2"),
                         tuple(outputs[key] for key in ("passed", "failed", "skipped", "core_failed")))

    def test_baseline_and_candidate_execute_identical_bounded_probe(self):
        self.assertIn('bash -euo pipefail -c "$GEM5_SMOKE"', self.steps["test5"]["run"])
        self.assertIn('bash -euo pipefail -c "$GEM5_SMOKE"', self.steps["test6"]["with"]["limited_cpu_probe"])
        self.assertEqual("false", self.steps["test6"]["with"]["defer_on_limited_cpu_probe_failure"])

    def test_two_build_deadlines_leave_bootstrap_and_orchestrator_headroom(self):
        smoke = self.job["env"]["GEM5_SMOKE"]
        match = re.search(r"timeout --kill-after=(\d+)s (\d+)m scons ", smoke)
        self.assertIsNotNone(match)
        kill_grace_seconds, build_minutes = map(int, match.groups())
        help_match = re.search(r"timeout (\d+)s build/NULL/gem5\.opt --help", smoke)
        self.assertIsNotNone(help_match)
        help_seconds = int(help_match.group(1))
        self.assertEqual(90, build_minutes)
        self.assertEqual(210, self.job["timeout-minutes"])
        bootstrap_minutes = 20
        bounded_seconds = 2 * (build_minutes * 60 + kill_grace_seconds + help_seconds)
        self.assertLess(bounded_seconds + bootstrap_minutes * 60,
                        self.job["timeout-minutes"] * 60)
        self.assertLess(self.job["timeout-minutes"], 330)
        wrapper = self.steps["test5"]["run"]
        self.assertIn("5m sudo docker pull", wrapper)
        self.assertIn("105m sudo docker run", wrapper)
        self.assertLess((5 + 105 + build_minutes) * 60 + 3 * 30 + help_seconds,
                        self.job["timeout-minutes"] * 60)

    def prepare_smoke(self):
        (self.root / "baseline-src/build/NULL").mkdir(parents=True)
        self.tool("scons", 'if [ -n "$BUILD_FAIL" ]; then echo "fixture compiler error"; exit 1; fi\n')
        binary = self.root / "baseline-src/build/NULL/gem5.opt"
        binary.write_text('#!/bin/sh\nif [ -n "$HELP_FAIL" ]; then echo "fixture help error"; exit 1; fi\necho "gem5 usage"\n')
        binary.chmod(0o755)

    def test_build_and_help_errors_are_visible_and_fail_the_real_smoke(self):
        self.prepare_smoke()
        for fault in ("BUILD_FAIL", "HELP_FAIL"):
            result, outputs = self.run_step("test5", **{fault: "1"})
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["status"])
            self.assertIn("fixture", result.stdout + result.stderr)
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])

    def test_only_baseline_uses_focal_and_explicit_compiler_environment(self):
        self.assertNotIn("container", self.job)
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertNotIn("CC", self.job["env"])
        self.assertNotIn("CXX", self.job["env"])
        self.assertRegex(self.job["env"]["PINNED_CONTAINER_IMAGE_GEM5"], r"^ubuntu@sha256:[0-9a-f]{64}$")
        wrapper = self.steps["test5"]["run"]
        self.assertIn("-e CC=gcc-10 -e CXX=g++-10", wrapper)
        self.assertIn('$SOURCE_DIR:/source:ro', wrapper)
        self.assertIn("cp -a --no-preserve=ownership /source /tmp/baseline-src", wrapper)
        self.assertIn("cd /tmp/baseline-src\n", wrapper)
        self.assertIn("rm -rf build", wrapper)
        self.assertNotIn("gcc-10", self.steps["Bootstrap baseline dependencies"]["with"]["packages"])
        for text in (self.job["env"]["GEM5_SMOKE"], self.steps["test6"]["with"]["limited_cpu_probe"]):
            for baseline_only in ("docker", "gcc-10", "g++-10", "PINNED_CONTAINER_IMAGE"):
                self.assertNotIn(baseline_only, text)

    def test_baseline_wrapper_bounds_resources_and_cleans_after_success(self):
        self.prepare_smoke()
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        calls = Path(self.env["DOCKER_CALLS"]).read_text()
        for argument in ("--platform\nlinux/arm64", "--cpus\n2", "--memory\n8g",
                         "--memory-swap\n8g", "--pids-limit\n512", "/source:ro", "CALL rm\nrm\n-f"):
            self.assertIn(argument, calls)
        names = re.findall(r"gem5-baseline-gem5-baseline\.[A-Za-z0-9]+", calls)
        self.assertTrue(names)
        self.assertEqual(1, len(set(names)))
        self.assertFalse(list(self.root.glob("gem5-baseline.*")))
        self.assertTrue((self.root / "baseline-src/build/NULL/gem5.opt").exists())

    def test_baseline_wrapper_pull_launch_and_timeout_failures_are_cleaned(self):
        self.prepare_smoke()
        for fault, code in (("PULL_FAIL", "1"), ("RUN_FAIL", "125"), ("RUN_FAIL", "124")):
            with self.subTest(fault=fault, code=code):
                Path(self.env["DOCKER_CALLS"]).write_text("")
                result, outputs = self.run_step("test5", **{fault: code})
                self.assertEqual(int(code), result.returncode)
                self.assertEqual("failed", outputs["status"])
                self.assertIn("duration", outputs)
                self.assertIn("CALL rm\nrm\n-f", Path(self.env["DOCKER_CALLS"]).read_text())
                self.assertFalse(list(self.root.glob("gem5-baseline.*")))

    def test_baseline_wrapper_rejects_missing_source_without_launching_docker(self):
        result, outputs = self.run_step("test5")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertFalse(Path(self.env["DOCKER_CALLS"]).exists())

if __name__ == "__main__":
    unittest.main()
