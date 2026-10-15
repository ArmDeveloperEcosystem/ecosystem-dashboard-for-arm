"""CUDA-QX source/compiler fixtures, not native Linux Arm or GPU validation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as observation_audit


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-cuda-qx.yml"
ACTION = WORKFLOW.parent.parent / "actions/generic-source-regression-check/action.yml"
HEADER = """#pragma once
#include <memory>
namespace cudaqx {
class tear_down {
public:
  virtual void runTearDown() const = 0;
  virtual ~tear_down() = default;
};
void scheduleTearDown(std::unique_ptr<tear_down>);
}
"""


def preflight_code(job):
    return job["env"]["CUDA_QX_CPU_PREFLIGHT"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]


class CudaQxWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-cuda-qx"]
        cls.steps = {step["id"]: step for step in cls.job["steps"] if "id" in step}
        cls.code = preflight_code(cls.job)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cuda-qx-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.output = self.root / "github-output"
        self.calls = 0
        self.env = dict(os.environ, GITHUB_OUTPUT=str(self.output), PYTHONDONTWRITEBYTECODE="1")

    def source(self, libraries="qec", directory="next-src"):
        root = self.root / directory
        files = {
            "CMakeLists.txt": f'set(CUDAQX_ALL_LIBS "{libraries}")\n',
            "libs/core/include/cuda-qx/core/tear_down.h": HEADER,
        }
        for library in libraries.split(";"):
            base = f"libs/{library}"
            files[f"{base}/CMakeLists.txt"] = "add_subdirectory(python)\n"
            files[f"{base}/python/CMakeLists.txt"] = "# Python bindings fixture\n"
            # If imported, this fails. Source compilation must not import it.
            files[f"{base}/python/cudaq_{library}/__init__.py"] = "import missing_gpu_runtime\n"
            files[f"{base}/python/cudaq_{library}/plugins/example.py"] = "def plugin():\n    return 1\n"
            suffixes = (".cu12", ".cu13") if libraries == "qec" else ("",)
            for suffix in suffixes:
                name = f"cudaq-{library}" + suffix.replace(".", "-")
                files[f"{base}/pyproject.toml{suffix}"] = f'[project]\nname = "{name}"\n'
        for relative, content in files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        return root

    def run_command(self, command, extra_env=None):
        self.output.write_text("")
        result = subprocess.run(
            command, cwd=self.root, env={**self.env, **(extra_env or {})},
            capture_output=True, text=True, timeout=45,
        )
        pairs = [line.split("=", 1) for line in self.output.read_text().splitlines()]
        outputs = dict(pairs)
        self.assertEqual(len(pairs), len(outputs), "duplicate GitHub output keys")
        evidence = os.environ.get("WORKFLOW_EVIDENCE_ROOT")
        if evidence:
            self.calls += 1
            target = Path(evidence) / self._testMethodName / str(self.calls)
            target.mkdir(parents=True, exist_ok=True)
            (target / "result.json").write_text(json.dumps({
                "command": command, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr, "outputs": outputs,
                "workflow_sha256": hashlib.sha256(WORKFLOW.read_bytes()).hexdigest(),
                "scope": "local source/compiler or shell fixture; not hosted Arm validation",
            }, indent=2) + "\n")
        return result, outputs

    def source_script(self, root, expected=""):
        # Invoke only the source verifier; do not spoof the workflow's Arm gate.
        return (
            f"namespace = {{'__name__': 'cudaqx_source_fixture'}}\n"
            f"exec(compile({self.code!r}, '<workflow-source-proof>', 'exec'), namespace)\n"
            f"namespace['verify_source'](namespace['Path']({str(root)!r}), {expected!r})\n"
        )

    def verify(self, root, expected=""):
        return self.run_command([sys.executable, "-B", "-c", self.source_script(root, expected)])[0]

    def assert_source_failed(self, root, message):
        result = self.verify(root)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        self.assertNotIn("cudaqx-source-preflight-ok:", result.stdout)

    def test_current_qec_only_and_legacy_qec_solvers_compile(self):
        for libraries, directory in (("qec", "next-src"), ("qec;solvers", "baseline-src")):
            with self.subTest(libraries=libraries):
                root = self.source(libraries, directory)
                result = self.verify(root)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn(f"libraries={libraries};", result.stdout)
                for library in libraries.split(";"):
                    self.assertIn(f"cudaq_{library} (2 files)", result.stdout)
                self.assertEqual([], list(root.rglob("*.pyc")))

    def test_baseline_still_requires_both_libraries(self):
        root = self.source()
        result = self.verify(root, "qec;solvers")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("expected CUDA-QX libraries qec;solvers", result.stderr)
        root = self.source("qec;solvers", "baseline-src")
        shutil.rmtree(root / "libs/solvers")
        self.assert_source_failed(root, "missing CUDA-QX source file: libs/solvers/CMakeLists.txt")

    def test_current_layout_requires_all_meaningful_files(self):
        required = (
            "CMakeLists.txt", "libs/core/include/cuda-qx/core/tear_down.h",
            "libs/qec/CMakeLists.txt", "libs/qec/python/CMakeLists.txt",
            "libs/qec/python/cudaq_qec/__init__.py",
        )
        for index, relative in enumerate(required):
            with self.subTest(relative=relative):
                root = self.source(directory=f"missing-{index}")
                (root / relative).unlink()
                self.assert_source_failed(root, f"missing CUDA-QX source file: {relative}")
        root = self.source()
        shutil.rmtree(root / "libs/qec/python/cudaq_qec")
        self.assert_source_failed(root, "missing CUDA-QX source file")

    def test_empty_or_unrecognized_declaration_fails_closed(self):
        for index, declaration in enumerate((
            "", '# set(CUDAQX_ALL_LIBS "qec")\n',
            'set(CUDAQX_ALL_LIBS "solvers")\n',
            'set(CUDAQX_ALL_LIBS "qec;unknown")\n',
            'set(CUDAQX_ALL_LIBS "qec")\nset(CUDAQX_ALL_LIBS "qec;solvers")\n',
        )):
            with self.subTest(declaration=declaration):
                root = self.source(directory=f"declaration-{index}")
                (root / "CMakeLists.txt").write_text(declaration)
                self.assert_source_failed(root, "CUDA-QX")

    def test_missing_malformed_and_wrong_package_metadata_fail(self):
        for index, content in enumerate((None, "[project", '[project]\nname = "not-cudaq-qec"\n')):
            with self.subTest(content=content):
                root = self.source(directory=f"metadata-{index}")
                for path in (root / "libs/qec").glob("pyproject.toml*"):
                    if content is None:
                        path.unlink()
                    else:
                        path.write_text(content)
                message = "TOMLDecodeError" if content == "[project" else "CUDA-QX"
                self.assert_source_failed(root, message)
        root = self.source()
        (root / "libs/qec/pyproject.toml.cu13").write_text('[project]\nname = "cudaq-qec-cu12"\n')
        self.assert_source_failed(root, "wrong CUDA-QX package identity")

    def test_python_syntax_failure_in_each_declared_library_fails(self):
        for library in ("qec", "solvers"):
            with self.subTest(library=library):
                root = self.source("qec;solvers", library)
                (root / f"libs/{library}/python/cudaq_{library}/plugins/example.py").write_text("def broken(:\n")
                self.assert_source_failed(root, "SyntaxError")

    def test_real_compiler_rejects_wrong_core_api(self):
        for index, header in enumerate((
            HEADER.replace("runTearDown", "wrongMethod"),
            HEADER.replace("() const", "()"),
            HEADER.replace("virtual ~tear_down()", "~tear_down()"),
            HEADER.replace("void scheduleTearDown", "int scheduleTearDown"),
        )):
            with self.subTest(index=index):
                root = self.source(directory=f"wrong-api-{index}")
                (root / "libs/core/include/cuda-qx/core/tear_down.h").write_text(header)
                self.assert_source_failed(root, "error:")

    def test_workflow_entry_rejects_non_linux_arm_runners(self):
        for system, machine in (("Linux", "x86_64"), ("Darwin", "arm64")):
            with self.subTest(system=system, machine=machine):
                script = (
                    "from unittest.mock import patch\n"
                    f"with patch('platform.system', return_value={system!r}), "
                    f"patch('platform.machine', return_value={machine!r}):\n"
                    f"    exec(compile({self.code!r}, '<workflow-entry>', 'exec'))\n"
                )
                result, _ = self.run_command([sys.executable, "-B", "-c", script])
                self.assertNotEqual(0, result.returncode)
                self.assertIn("requires a Linux Arm64 runner", result.stderr)

    def render(self, script, values):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if values.get(term):
                    return values[term]
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)

    def summary(self, statuses=None, outcomes=None):
        values = {}
        for number in range(1, 7):
            step = f"test{number}"
            values[f"steps.{step}.outputs.status"] = (statuses or {}).get(step, "passed")
            values[f"steps.{step}.outputs.duration"] = "2"
            values[f"steps.{step}.outcome"] = (outcomes or {}).get(step, "success")
        return self.run_command([
            "bash", "-euo", "pipefail", "-c", self.render(self.steps["summary"]["run"], values),
        ])

    def test_summary_accepts_pass_and_explicit_successful_skip(self):
        for status in ("passed", "skipped"):
            result, output = self.summary({"test6": status})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("6" if status == "passed" else "5", output["passed"])
            self.assertEqual("0" if status == "passed" else "1", output["skipped"])
            self.assertEqual("0", output["failed"])
            self.assertEqual("success", output["overall_status"])
            self.assertEqual(status, output["test6_status"])

    def test_summary_failed_missing_or_invalid_outputs_are_not_skips(self):
        for number in range(1, 7):
            for status in ("failed", "", "invalid", "skipped"):
                if number == 6 and status == "skipped":
                    continue
                with self.subTest(number=number, status=status):
                    result, output = self.summary({f"test{number}": status})
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertEqual("5", output["passed"])
                    self.assertEqual("1", output["failed"])
                    self.assertEqual("0", output["skipped"])
                    self.assertEqual("failure", output["overall_status"])
                    self.assertEqual("0" if number == 6 else "1", output["core_failed"])
                    self.assertEqual("passing" if number == 6 else "failing", output["badge_status"])
                    self.assertEqual("12", output["duration"])

    def test_summary_raw_outcomes_override_passed_or_skipped_output(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", "skipped", ""):
                for status in ("passed", "skipped"):
                    with self.subTest(number=number, outcome=outcome, status=status):
                        result, output = self.summary({f"test{number}": status}, {f"test{number}": outcome})
                        self.assertEqual(1, result.returncode, result.stderr)
                        self.assertEqual("5", output["passed"])
                        self.assertEqual("1", output["failed"])
                        self.assertEqual("0", output["skipped"])
                        if number == 6:
                            self.assertEqual("failed", output["test6_status"])

    def test_summary_all_absent_fails_with_six_failures(self):
        empty = {f"test{n}": "" for n in range(1, 7)}
        result, output = self.summary(empty, empty)
        self.assertEqual(1, result.returncode)
        self.assertEqual("6", output["failed"])
        self.assertEqual("5", output["core_failed"])
        self.assertEqual("0", output["passed"])
        self.assertEqual("0", output["skipped"])

    def test_generic_action_zero_exit_after_failure_is_enforced_by_caller(self):
        action = yaml.safe_load(ACTION.read_text())["runs"]["steps"][0]["run"]
        function = action.split("run_limited_cpu_probe() {", 1)[1].split('\nif [ -z "$REPO" ]', 1)[0]
        function = "run_limited_cpu_probe() {" + function
        result, output = self.run_command([
            "bash", "-euo", "pipefail", "-c", function + '\nrun_limited_cpu_probe "0.8.0" "0.8.0"',
        ], {
            "LIMITED_CPU_PROBE": "echo 'fixture preflight failure' >&2; exit 42",
            "LIMITED_CPU_DESCRIPTION": self.steps["test6"]["with"]["limited_cpu_description"],
            "DEFER_ON_LIMITED_CPU_PROBE_FAILURE": "false", "CURRENT": "0.2.0",
            "REPO": "NVIDIA/cudaqx", "LANE_KIND": self.job["env"]["LANE_KIND"],
        })
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("failed", output["status"])
        self.assertEqual("limited_cpu_smoke_failed", output["decision"])
        self.assertNotIn("smoke_validated", output["comparison"])
        result, summary = self.summary({"test6": output["status"]})
        self.assertEqual(1, result.returncode)
        self.assertEqual("failure", summary["overall_status"])
        self.assertEqual("1", summary["failed"])

    def test_baseline_wrapper_preserves_failure_diagnostics_and_duration(self):
        # Portable fixture for GNU timeout, which the Ubuntu runner supplies.
        binary = self.root / "bin"
        binary.mkdir()
        timeout = binary / "timeout"
        timeout.write_text(
            f"#!{sys.executable}\nimport subprocess, sys\n"
            "try:\n    sys.exit(subprocess.run(sys.argv[2:], timeout=float(sys.argv[1][:-1])).returncode)\n"
            "except subprocess.TimeoutExpired:\n    sys.exit(124)\n"
        )
        timeout.chmod(0o755)
        script = self.render(self.steps["test5"]["run"], {"steps.install.outputs.install_mode": "github_source"})
        for exit_code in (0, 42, 124):
            with self.subTest(exit_code=exit_code):
                result, output = self.run_command(["bash", "-euo", "pipefail", "-c", script], {
                    "PATH": f"{binary}:{os.environ['PATH']}",
                    "CUDA_QX_CPU_PREFLIGHT": f"echo 'fixture diagnostic' >&2; exit {exit_code}",
                })
                self.assertEqual(exit_code, result.returncode, result.stderr)
                self.assertEqual("passed" if exit_code == 0 else "failed", output["status"])
                self.assertRegex(output["duration"], r"^\d+$")
                self.assertIn("fixture diagnostic", result.stderr)

    def test_candidate_policy_runner_and_cpu_only_scope_are_preserved(self):
        self.assertEqual("0.2.0", self.job["env"]["BASELINE_VERSION"])
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        candidate = self.steps["test6"]["with"]
        self.assertEqual("./.github/actions/generic-source-regression-check", self.steps["test6"]["uses"])
        for key in ("next_version_override", "candidate_tag_override", "defer_on_limited_cpu_probe_failure"):
            self.assertNotIn(key, candidate)
        self.assertIn("PREFLIGHT_SOURCE_DIR=next-src", candidate["limited_cpu_probe"])
        self.assertIn("PREFLIGHT_EXPECTED_LIBS='qec;solvers'", self.steps["test5"]["run"])
        for script in (candidate["limited_cpu_probe"], self.steps["test5"]["run"]):
            self.assertIn('timeout 120s bash -euo pipefail -c "$CUDA_QX_CPU_PREFLIGHT"', script)
        self.assertIn("No package installation, CUDA-Q, GPU, or QPU runtime execution is claimed", candidate["limited_cpu_description"])
        self.assertEqual("always()", self.steps["summary"]["if"])
        self.assertNotIn("continue-on-error", self.steps["summary"])
        self.assertIn("steps.summary.outputs.test6_status", self.job["outputs"]["regression_status"])

    def test_unchanged_auditor_sees_test5_status_and_duration(self):
        root = WORKFLOW.parents[2]
        for output in ("status", "duration"):
            self.assertTrue(observation_audit._step_emits_output(root, self.steps["test5"], output), output)
        self.assertEqual(
            {"passed", "failed"},
            set(observation_audit._step_literal_outputs(root, self.steps["test5"], "status")),
        )
        self.assertTrue(self.steps["test5"]["run"].rstrip().endswith("finish 0"))


if __name__ == "__main__":
    unittest.main()
