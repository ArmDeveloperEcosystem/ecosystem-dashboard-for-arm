"""Exercise the legacy gdspy runtime, diagnostics, and fail-closed summary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-gdspy.yml"


class GdspyWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="gdspy-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-gdspy"]
        self.steps = {step.get("id", step["name"]): step for step in job["steps"]}
        self.env = dict(os.environ, **job["env"])
        self.env.update(
            BASELINE_CONTAINER="gdspy-fixture-baseline", NEXT_CONTAINER="gdspy-fixture-next",
            GITHUB_OUTPUT=str(self.root / "output"), DOCKER_CALLS=str(self.root / "calls"),
            PYTHONPATH=str(self.root), FIXTURE_PYTHON=sys.executable,
        )
        tools = self.root / "bin"
        tools.mkdir()
        self.env["PATH"] = str(tools) + os.pathsep + os.environ["PATH"]
        (self.root / ".venv-lookup/bin").mkdir(parents=True)
        (self.root / ".venv-lookup/bin/activate").write_text("")
        (tools / "python").write_text('#!/bin/sh\nprintf "%s\\n" "${LOOKUP_RESULT-0.3}"\n')
        (tools / "python").chmod(0o755)
        (tools / "docker").write_text(f"#!{sys.executable}\n" + '''
import json
import os
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
with open(os.environ["DOCKER_CALLS"], "a") as calls:
    calls.write(json.dumps(args) + "\\n")
if args[0] == "run":
    assert args[1:3] == ["-d", "--name"]
    assert args[4] == os.environ["PINNED_CONTAINER_IMAGE_GDSPY"]
    assert args[5:] == ["sleep", "infinity"]
    if os.environ.get("RUN_FAIL"):
        sys.exit("container start failed")
    print(args[3])
elif args[0] == "exec":
    args.pop(0)
    env = dict(os.environ)
    if args[0] == "-e":
        key, value = args[1].split("=", 1)
        env[key] = value
        del args[:2]
    container = args.pop(0)
    env["FIXTURE_VERSION"] = "0.3" if container.endswith("next") else "0.2.9"
    if args[:4] == ["python", "-m", "pip", "install"]:
        assert args[4:] == ["numpy==1.16.6", "gdspy==" + env["FIXTURE_VERSION"]]
        if env.get("INSTALL_FAIL"):
            sys.exit("native extension build failed")
    elif args[:3] == ["python", "-m", "pip"]:
        if env.get("MISSING_PACKAGE"):
            sys.exit("package not installed")
    elif args == ["uname", "-m"]:
        print(env.get("CONTAINER_ARCH", "aarch64"))
    else:
        assert args[:2] == ["python", "-c"]
        sys.exit(subprocess.run([env["FIXTURE_PYTHON"], *args[1:]], env=env).returncode)
elif args[0] == "container":
    assert args[1] == "inspect"
elif args[0] == "rm":
    assert args[1] == "-f"
    assert args[2] in (os.environ["BASELINE_CONTAINER"], os.environ["NEXT_CONTAINER"])
else:
    raise AssertionError(args)
''')
        (tools / "docker").chmod(0o755)
        (tools / "uname").write_text('#!/bin/sh\nprintf "%s\\n" "${HOST_ARCH-aarch64}"\n')
        (tools / "uname").chmod(0o755)
        (self.root / "pkg_resources.py").write_text('''
import os
class Distribution:
    version = os.environ.get("WRONG_VERSION", os.environ.get("FIXTURE_VERSION", "0.2.9"))
    def has_metadata(self, name):
        return not os.environ.get("MISSING_FILES")
    def get_metadata(self, name):
        return "gdspy/boolext.so"
def get_distribution(name):
    return Distribution()
''')
        (self.root / "numpy.py").write_text('__version__ = "1.16.6"\n')
        (self.root / "gdspy.py").write_text('''
import os
if os.environ.get("IMPORT_FAIL"):
    raise ImportError("undefined symbol: PyInt_FromLong")
__version__ = os.environ.get("MODULE_VERSION", os.environ.get("FIXTURE_VERSION", "0.2.9"))
class Rectangle:
    def __init__(self, layer, point1, point2):
        self.layer, self.point1, self.point2 = layer, point1, point2
    def area(self):
        if os.environ.get("RECTANGLE_FAIL"):
            return 0
        return (self.point2[0] - self.point1[0]) * (self.point2[1] - self.point1[1])
def boolean(layer, objects, operation):
    assert operation(1, 1) and not operation(1, 0)
    if os.environ.get("BOOLEAN_NONE"):
        return None
    return Rectangle(layer, (1, 0), (2, 0 if os.environ.get("BOOLEAN_FAIL") else 3))
''')

    def run_step(self, name, statuses=None, outcomes=None, **env):
        values = {f"steps.{key}.outputs.status": value for key, value in (statuses or {}).items()}
        values["steps.version.outputs.version"] = "0.2.9"
        if outcomes is None:
            outcomes = {f"test{n}": "success" for n in range(1, 7)}
        values.update({f"steps.{key}.outcome": value for key, value in outcomes.items()})

        def render(script):
            def expression(match):
                for term in match.group(1).split("||"):
                    term = term.strip()
                    if term.startswith("'"):
                        return term.strip("'")
                    value = values.get(term) or (self.env.get(term[4:]) if term.startswith("env.") else None)
                    if value:
                        return value
                return ""
            return re.sub(r"\$\{\{ (.*?) \}\}", expression, script)

        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        step = self.steps[name]
        step_env = {key: render(value) for key, value in step.get("env", {}).items()}
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", render(step["run"])],
            cwd=self.root, env=dict(self.env, **step_env, **env),
            capture_output=True, text=True, timeout=10,
        )
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def test_baseline_checks_use_the_installed_legacy_container(self) -> None:
        self.assertEqual("0.2.9", self.env["BASELINE_VERSION"])
        self.assertEqual(
            "python@sha256:d8fac68ebdc45b8d66d53f1ed6c1532da81109a8f5532a6ca0c951ed31107d70",
            self.env["PINNED_CONTAINER_IMAGE_GDSPY"],
        )
        self.assertIn("# original: python:2.7.18-buster", WORKFLOW.read_text())
        for step in ("test1", "test2", "test3", "test4", "test5"):
            with self.subTest(step=step):
                result, outputs = self.run_step(step)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("passed", outputs["status"])
                if step == "test5":
                    self.assertIn(self.env["VALIDATION_SCOPE"], outputs["note"])

    def test_missing_package_files_version_and_architecture_fail(self) -> None:
        cases = (("test1", "MISSING_PACKAGE", "1"), ("test2", "WRONG_VERSION", "0.3"),
                 ("test3", "MISSING_FILES", "1"), ("test4", "CONTAINER_ARCH", "x86_64"),
                 ("test4", "HOST_ARCH", "x86_64"))
        for step, key, value in cases:
            with self.subTest(step=step, key=key):
                result, outputs = self.run_step(step, **{key: value})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])

    def test_both_versions_reject_import_geometry_and_module_version_failures(self) -> None:
        for step in ("test5", "test6"):
            for failure in ("IMPORT_FAIL", "RECTANGLE_FAIL", "BOOLEAN_NONE", "BOOLEAN_FAIL", "MODULE_VERSION"):
                with self.subTest(step=step, failure=failure):
                    result, outputs = self.run_step(step, **{failure: "1"})
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", outputs["status"])
                    self.assertIn("Traceback", result.stderr)
                    if failure == "IMPORT_FAIL":
                        self.assertIn("undefined symbol: PyInt_FromLong", result.stderr)
                    if step == "test6":
                        self.assertEqual("next_install_failed", outputs["decision"])

    def test_candidate_success_reports_actual_baseline_status(self) -> None:
        for state in ("passed", "failed", ""):
            with self.subTest(state=state):
                result, outputs = self.run_step("test6", statuses={"test5": state})
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("passed", outputs["status"])
                self.assertEqual("0.3", outputs["next_installed_version"])
                self.assertIn(f"functional validation: {state or 'failed'}", outputs["comparison"])
                self.assertIn("legacy Python 2.7", outputs["comparison"])
                self.assertIn(self.env["VALIDATION_SCOPE"], outputs["comparison"])

    def test_candidate_comparison_reports_late_baseline_failure(self) -> None:
        result, outputs = self.run_step(
            "test6", statuses={"test5": "passed"}, outcomes={"test5": "failure"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertIn("functional validation: failed", outputs["comparison"])

    def test_candidate_start_install_version_and_lookup_failures(self) -> None:
        for key, value in (("RUN_FAIL", "1"), ("INSTALL_FAIL", "1"), ("WRONG_VERSION", "0.4"),
                           ("LOOKUP_RESULT", "lookup_failed")):
            with self.subTest(key=key):
                result, outputs = self.run_step("test6", **{key: value})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])
                self.assertNotEqual("next_install_validated", outputs["decision"])

    def test_no_new_candidate_is_skipped_without_starting_container(self) -> None:
        result, outputs = self.run_step("test6", LOOKUP_RESULT="")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("skipped", outputs["status"])
        self.assertEqual("no_newer_stable_available", outputs["decision"])
        self.assertFalse(Path(self.env["DOCKER_CALLS"]).exists())

    def test_cleanup_removes_only_its_two_containers(self) -> None:
        result, _ = self.run_step("Cleanup")
        self.assertEqual(0, result.returncode, result.stderr)
        calls = [json.loads(line) for line in Path(self.env["DOCKER_CALLS"]).read_text().splitlines()]
        self.assertEqual(
            [["rm", "-f", self.env[key]] for key in ("BASELINE_CONTAINER", "NEXT_CONTAINER")],
            [args for args in calls if args[0] == "rm"],
        )

    def test_summary_preserves_every_failure_and_only_skips_candidate(self) -> None:
        for changed in (None, "all", "test1", "test2", "test3", "test4", "test5", "test6"):
            for state in ("failed", "", "invalid", "skipped"):
                with self.subTest(changed=changed, state=state):
                    statuses = {f"test{n}": "passed" for n in range(1, 7)}
                    if changed == "all":
                        statuses = {}
                    elif changed:
                        statuses[changed] = state
                    result, outputs = self.run_step("summary", statuses=statuses)
                    skipped = int(changed == "test6" and state == "skipped")
                    failed = 6 if changed == "all" else int(changed is not None and not skipped)
                    core = 5 if changed == "all" else int(changed not in (None, "test6"))
                    self.assertEqual(int(failed > 0), result.returncode, result.stderr)
                    self.assertEqual(str(failed), outputs["failed"])
                    self.assertEqual(str(core), outputs["core_failed"])
                    self.assertEqual(str(6 - failed - skipped), outputs["passed"])
                    self.assertEqual(str(skipped), outputs["skipped"])
                    self.assertEqual("failure" if failed else "success", outputs["overall_status"])
                    self.assertEqual("failing" if core else "passing", outputs["badge_status"])

    def test_passed_output_cannot_hide_unsuccessful_or_missing_outcome(self) -> None:
        statuses = {f"test{n}": "passed" for n in range(1, 7)}
        for number in range(1, 7):
            for outcome in ("failure", "skipped", "cancelled", ""):
                with self.subTest(number=number, outcome=outcome):
                    outcomes = {f"test{n}": "success" for n in range(1, 7)}
                    outcomes[f"test{number}"] = outcome
                    result, outputs = self.run_step("summary", statuses=statuses, outcomes=outcomes)
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertEqual("5", outputs["passed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual("0", outputs["skipped"])
                    self.assertEqual("1" if number <= 5 else "0", outputs["core_failed"])
                    self.assertEqual("failure", outputs["overall_status"])
                    self.assertEqual("failing" if number <= 5 else "passing", outputs["badge_status"])
        result, outputs = self.run_step("summary", statuses=statuses, outcomes={})
        self.assertEqual(1, result.returncode)
        self.assertEqual("6", outputs["failed"])
        self.assertEqual("5", outputs["core_failed"])

    def test_candidate_skip_requires_successful_outcome(self) -> None:
        statuses = {f"test{n}": "passed" for n in range(1, 6)}
        statuses["test6"] = "skipped"
        for outcome in ("failure", "skipped", "cancelled", ""):
            with self.subTest(outcome=outcome):
                outcomes = {f"test{n}": "success" for n in range(1, 6)}
                outcomes["test6"] = outcome
                result, outputs = self.run_step("summary", statuses=statuses, outcomes=outcomes)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("0", outputs["skipped"])
                self.assertEqual("0", outputs["core_failed"])
                self.assertEqual("failure", outputs["overall_status"])


if __name__ == "__main__":
    unittest.main()
