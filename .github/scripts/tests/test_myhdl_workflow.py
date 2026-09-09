"""Regression guards for real legacy MyHDL simulation and truthful accounting."""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as observation_audit


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-myhdl.yml"


class MyhdlWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-myhdl"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        temporary = tempfile.TemporaryDirectory(prefix="myhdl-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def render(self, script, overrides=None):
        values = {f"steps.test{i}.{key}": value for i in range(1, 7)
                  for key, value in (("outputs.status", "passed"), ("outcome", "success"))}
        values.update(overrides or {})
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else values.get(term, "")
                if value:
                    return value
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)

    def run_step(self, name, overrides=None, **environment):
        output = self.root / "output"
        output.write_text("")
        env = dict(os.environ, **self.job["env"])
        env.update(GITHUB_OUTPUT=str(output), GITHUB_WORKSPACE=str(self.root), RUNNER_TEMP=str(self.root),
                   PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        env.update(environment)
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", self.render(self.steps[name]["run"], overrides)],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def docker_fixture(self, run_exit=0):
        timeout = self.bin / "timeout"
        timeout.write_text('#!/bin/bash\nshift 3\nexec "$@"\n')
        timeout.chmod(0o755)
        sudo = self.bin / "sudo"
        sudo.write_text("#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
                        + f'if [ "$2" = run ]; then exit {run_exit}; fi\nexit 0\n')
        sudo.chmod(0o755)
        archive = self.root / "baseline-runtime/myhdl.tar.gz"
        archive.parent.mkdir(exist_ok=True)
        archive.write_bytes(b"unit-test fixture, not runtime evidence")
        return dict(CALL_LOG=str(self.root / "calls"), MYHDL_BASELINE_SHA256=hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_baseline_is_unchanged_and_official_archive_and_image_are_pinned(self):
        self.assertEqual("0.8", self.job["env"]["BASELINE_VERSION"])
        self.assertEqual("python@sha256:d8fac68ebdc45b8d66d53f1ed6c1532da81109a8f5532a6ca0c951ed31107d70", self.job["env"]["PINNED_CONTAINER_IMAGE_MYHDL"])
        self.assertEqual("fe69b3c834225bdb7348f7b86160bbc3368d14a90191cd49d063b7a751b4b5e1", self.job["env"]["MYHDL_BASELINE_SHA256"])
        self.assertTrue(self.job["env"]["MYHDL_BASELINE_URL"].startswith("https://files.pythonhosted.org/"))

    def test_all_outputs_are_visible_to_existing_observation_audit(self):
        for number in range(1, 7):
            for output in ("status", "duration"):
                with self.subTest(number=number, output=output):
                    self.assertTrue(observation_audit._step_emits_output(
                        WORKFLOW.parents[2], self.steps[f"test{number}"], output,
                    ))

    def test_simulation_is_network_disabled_and_resource_bounded(self):
        script = self.steps["test5"]["run"]
        for flag in ("--network none", "--read-only", "--cpus 2", "--memory 1g", "--memory-swap 1g", "--no-index", "--no-deps", "--platform linux/arm64"):
            self.assertIn(flag, script)
        self.assertIn('"$WORKDIR:/inputs:ro"', script)
        self.assertNotIn("docker.sock", script)
        self.assertNotIn("status=skipped", script)

    def test_baseline_wrong_version_fails_with_duration(self):
        result, outputs = self.run_step("test5", BASELINE_VERSION="0.9", **self.docker_fixture())
        self.assertEqual(1, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertTrue(outputs["duration"].isdigit())

    def test_corrupt_archive_never_reaches_container_execution(self):
        environment = self.docker_fixture()
        environment["MYHDL_BASELINE_SHA256"] = "0" * 64
        result, outputs = self.run_step("test5", **environment)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertNotIn("docker run", (self.root / "calls").read_text())

    def test_container_failure_propagates_without_skip(self):
        result, outputs = self.run_step("test5", **self.docker_fixture(run_exit=19))
        self.assertEqual(19, result.returncode, result.stderr)
        self.assertEqual("failed", outputs["status"])
        self.assertTrue(outputs["duration"].isdigit())
        self.assertIn("docker rm -f myhdl-baseline-", (self.root / "calls").read_text())

    def test_simulation_runtime_version_and_install_location_are_checked(self):
        script = self.job["env"]["MYHDL_SIMULATION"]
        for version, location in (("0.7", "/tmp/site/myhdl/__init__.py"), ("0.8.1", "/tmp/site/myhdl/__init__.py"), ("0.8", "/uninstalled/myhdl/__init__.py")):
            with self.subTest(version=version, location=location):
                harness = (
                    "import sys, types, platform\n"
                    "m = types.ModuleType('myhdl')\n"
                    f"m.__version__ = {version!r}\nm.__file__ = {location!r}\n"
                    "for name in ('Signal', 'intbv', 'modbv', 'delay', 'instance', 'always_comb', 'always', 'Simulation', 'StopSimulation'): setattr(m, name, None)\n"
                    "sys.modules['myhdl'] = m\nplatform.machine = lambda: 'aarch64'\n"
                    f"exec(compile({script!r}, 'workflow-simulation.py', 'exec'))\n"
                )
                result = subprocess.run([sys.executable, "-c", harness], env=dict(os.environ, EXPECTED_VERSION="0.8"), capture_output=True, text=True, timeout=10)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("AssertionError", result.stderr)

    def test_adder_and_counter_assertions_remain_functional(self):
        script = self.job["env"]["MYHDL_SIMULATION"]
        for check in ("Simulation(bench()).run()", "assert int(total) == left + right", "assert int(count) == (tick + 1) % 16", "count.next = (count + 1) % 16", "@always(clock.posedge)", "range(32)"):
            self.assertIn(check, script)

    def test_candidate_keeps_exact_version_simulation_and_verilog_conversion(self):
        candidate = self.steps["test6"]["with"]
        self.assertNotEqual("true", candidate.get("defer_on_limited_cpu_probe_failure"))
        probe = candidate["limited_cpu_probe"]
        for check in ('assert myhdl.__version__ == os.environ["LATEST_VERSION"]', 'assert importlib.metadata.version("myhdl") == os.environ["LATEST_VERSION"]', "sim.run()", "toVerilog(inverter, a, b)", '"module myhdl_inverter" in out.read_text'):
            self.assertIn(check, probe)
        self.assertIn("--require-hashes", probe)
        self.assertIn("--no-index --no-deps --no-build-isolation ./next-src", probe)

    def test_candidate_socket_operations_are_actually_denied(self):
        probe = self.steps["test6"]["with"]["limited_cpu_probe"]
        code = probe[probe.index("def deny_network"):probe.index("from myhdl import Signal")]
        result = subprocess.run([sys.executable, "-c", "import sys, socket\n" + code + "\nsocket.socket()\n"], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Network is disabled during the candidate simulation", result.stderr)

    def test_candidate_module_and_distribution_versions_are_both_required(self):
        probe = self.steps["test6"]["with"]["limited_cpu_probe"]
        assertions = probe[probe.index("import os\n"):probe.index("def deny_network")]
        for runtime, metadata in (("0.8", "0.11.51"), ("0.11.51", "0.8"), ("0.11.510", "0.11.510")):
            prelude = ("import sys, types, importlib.metadata\n"
                       "m = types.ModuleType('myhdl')\n"
                       f"m.__version__ = {runtime!r}\n"
                       "m.__file__ = sys.prefix + '/lib/myhdl/__init__.py'\n"
                       "sys.modules['myhdl'] = m\n"
                       f"importlib.metadata.version = lambda name: {metadata!r}\n")
            result = subprocess.run([sys.executable, "-c", prelude + assertions],
                                    env=dict(os.environ, LATEST_VERSION="0.11.51"), capture_output=True, text=True, timeout=10)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("AssertionError", result.stderr)

    def test_original_unconditional_skip_is_a_core_failure(self):
        result, outputs = self.run_step("summary", {"steps.test5.outputs.status": "skipped"})
        self.assertEqual(1, result.returncode)
        self.assertEqual(("5", "1", "0", "1", "failure"), tuple(outputs[k] for k in ("passed", "failed", "skipped", "core_failed", "overall_status")))

    def test_failed_or_missing_outcome_cannot_be_counted_as_pass(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(number=number, outcome=outcome):
                    result, outputs = self.run_step("summary", {f"steps.test{number}.outcome": outcome})
                    self.assertEqual(1, result.returncode)
                    self.assertEqual("1", outputs["failed"])

    def test_missing_status_and_deferred_candidate_are_failures(self):
        for number in range(1, 7):
            result, outputs = self.run_step("summary", {f"steps.test{number}.outputs.status": ""})
            self.assertEqual(1, result.returncode)
            self.assertEqual("1", outputs["failed"])
        result, outputs = self.run_step("summary", {"steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": "runtime_validation_not_automated"})
        self.assertEqual(1, result.returncode)
        self.assertEqual("0", outputs["skipped"])

    def test_six_passes_and_only_explicit_no_newer_na(self):
        result, outputs = self.run_step("summary")
        self.assertEqual((0, "6", "0", "0"), (result.returncode, outputs["passed"], outputs["failed"], outputs["skipped"]))
        result, outputs = self.run_step("summary", {"steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": "no_newer_stable_available"})
        self.assertEqual((0, "5", "0", "1"), (result.returncode, outputs["passed"], outputs["failed"], outputs["skipped"]))


if __name__ == "__main__":
    unittest.main()
