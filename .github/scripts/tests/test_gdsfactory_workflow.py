"""Execute the embedded GDS probes and fail-closed workflow summary with fixtures."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-gdsfactory.yml"


class GdsfactoryWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gdsfactory-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-gdsfactory"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = dict(os.environ, **self.job["env"], GITHUB_OUTPUT=str(self.root / "output"),
                        TMPDIR=str(self.root), PYTHONPATH=str(self.root),
                        FIXTURE_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.metadata = self.root / "gdsfactory-9.9.4.dist-info/METADATA"
        self.metadata.parent.mkdir()
        package = self.root / "gdsfactory"
        package.mkdir()
        (package / "__init__.py").write_text('''
import json
import os
from pathlib import Path
from types import SimpleNamespace

if os.environ.get("FIXTURE_IMPORT_FAIL"):
    raise ImportError("fixture import failure")
__version__ = os.environ["FIXTURE_EXPECTED"]

def record(event):
    with open("events.jsonl", "a") as stream:
        stream.write(json.dumps(event) + "\\n")

def rectangle(size, layer):
    assert Path("pdk-active").exists()
    assert size == (10, 5) and layer == (1, 0), (size, layer)
    record(["rectangle", size, layer])
    return "rectangle-reference"

components = SimpleNamespace(rectangle=rectangle)

class Component:
    def __init__(self, name):
        assert name in ("arm_smoke", "arm_next_smoke"), name
        self.name = name
        self.reference = None

    def add_ref(self, reference):
        assert reference == "rectangle-reference"
        self.reference = reference

    def write_gds(self, filename):
        assert self.reference == "rectangle-reference"
        assert filename == self.name + ".gds", filename
        record(["write_gds", filename])
        mode = os.environ.get("FIXTURE_WRITE_MODE", "nonempty")
        if mode == "error":
            raise OSError("fixture write failure")
        if mode != "missing":
            # Unit-only bytes; native replay separately retains real GDS artifacts.
            Path(filename).write_bytes(b"fixture bytes" if mode == "nonempty" else b"")
''')
        (package / "generic_tech.py").write_text('''
from pathlib import Path

class PDK:
    def activate(self):
        Path("pdk-active").touch()

def get_generic_pdk():
    return PDK()
''')
        self.executable("python", f"#!{sys.executable}\n" + '''
import json
import os
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
with open("python-calls.jsonl", "a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args[:2] == ["-m", "venv"]:
    if os.environ.get("FIXTURE_VENV_FAIL"):
        sys.exit(11)
    target = Path(args[2]) / "bin"
    target.mkdir(parents=True, exist_ok=True)
    (target / "activate").write_text("")
elif args[:3] == ["-m", "pip", "install"]:
    if args[3:] == ["--upgrade", "pip", "setuptools", "wheel"]:
        sys.exit(0)
    assert args[3:] == ["gdsfactory==" + os.environ["FIXTURE_EXPECTED"]], args
    if os.environ.get("FIXTURE_INSTALL_FAIL"):
        sys.exit(12)
elif args == ["-"]:
    sys.exit(subprocess.run([os.environ["FIXTURE_PYTHON"], "-"],
                           input=sys.stdin.read(), text=True).returncode)
else:
    raise AssertionError(args)
''')
        self.executable("timeout", '#!/bin/bash\nset -euo pipefail\n'
                        'test "$1" = 300\nshift\nexec "$@"\n')

    def executable(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_script(self, script, values=None, **env):
        values = values or {}

        def expression(match):
            for part in match[1].split("||"):
                key = part.strip()
                value = (key[1:-1] if key.startswith("'") else
                         self.env.get(key[4:]) if key.startswith("env.") else values.get(key))
                if value:
                    return str(value)
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=20)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def run_probe(self, candidate=False, installed_version=None, **env):
        expected = "9.10.0" if candidate else self.env["BASELINE_VERSION"]
        actual = expected if installed_version is None else installed_version
        self.metadata.write_text(f"Metadata-Version: 2.1\nName: gdsfactory\nVersion: {actual}\n")
        for name in ("arm_smoke.gds", "arm_next_smoke.gds", "events.jsonl", "pdk-active"):
            (self.root / name).unlink(missing_ok=True)
        script = (self.steps["test6"]["with"]["limited_cpu_probe"] if candidate else
                  self.steps["test5"]["run"])
        return self.run_script(script, FIXTURE_EXPECTED=expected, LATEST_VERSION=expected, **env)

    def passing_values(self):
        return {key: value for i in range(1, 7) for key, value in (
            (f"steps.test{i}.outputs.status", "passed"), (f"steps.test{i}.outcome", "success"))}

    def test_preserves_python_baseline_and_real_candidate_probe(self):
        self.assertEqual("9.9.4", self.env["BASELINE_VERSION"])
        setups = [step for step in self.job["steps"]
                  if step.get("uses", "").startswith("actions/setup-python@")]
        self.assertEqual(["3.12", "3.12"], [step["with"]["python-version"] for step in setups])
        self.assertEqual("./.github/actions/generic-source-regression-check", self.steps["test6"]["uses"])
        self.assertNotIn("defer_on_limited_cpu_probe_failure", self.steps["test6"]["with"])

    def test_both_embedded_probes_activate_pdk_and_write_expected_geometry(self):
        for candidate in (False, True):
            with self.subTest(candidate=candidate):
                result, outputs = self.run_probe(candidate)
                self.assertEqual(0, result.returncode, result.stderr)
                name = "arm_next_smoke.gds" if candidate else "arm_smoke.gds"
                self.assertGreater((self.root / name).stat().st_size, 0)
                events = [json.loads(line) for line in (self.root / "events.jsonl").read_text().splitlines()]
                self.assertEqual([["rectangle", [10, 5], [1, 0]], ["write_gds", name]], events)
                if not candidate:
                    self.assertEqual("passed", outputs["status"])
                    self.assertIn("duration", outputs)

    def test_distribution_version_mismatch_cannot_hide_behind_module_version(self):
        for candidate in (False, True):
            for actual in ("0.0.0", "", "9.9.4" if candidate else "9.10.0"):
                with self.subTest(candidate=candidate, actual=actual):
                    result, outputs = self.run_probe(candidate, installed_version=actual)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("AssertionError", result.stderr)
                    self.assertFalse((self.root / "pdk-active").exists())
                    self.assertFalse((self.root / "events.jsonl").exists())
                    if not candidate:
                        self.assertEqual("failed", outputs["status"])
                        self.assertIn("duration", outputs)

    def test_missing_empty_or_failed_gds_write_fails_both_probes(self):
        for candidate in (False, True):
            for mode in ("missing", "empty", "error"):
                with self.subTest(candidate=candidate, mode=mode):
                    result, outputs = self.run_probe(candidate, FIXTURE_WRITE_MODE=mode)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("Traceback", result.stderr)
                    if not candidate:
                        self.assertEqual("failed", outputs["status"])
                        self.assertIn("duration", outputs)

    def test_environment_install_and_import_failures_are_not_passes(self):
        for candidate in (False, True):
            for failure in ("FIXTURE_VENV_FAIL", "FIXTURE_INSTALL_FAIL", "FIXTURE_IMPORT_FAIL"):
                with self.subTest(candidate=candidate, failure=failure):
                    result, outputs = self.run_probe(candidate, **{failure: "1"})
                    self.assertNotEqual(0, result.returncode)
                    self.assertNotEqual("passed", outputs.get("status"))
                    if not candidate:
                        self.assertEqual("failed", outputs["status"])
                        self.assertIn("duration", outputs)

    def test_late_failure_after_passed_output_is_recorded_by_trap_and_summary(self):
        self.executable("date", '#!/bin/bash\nset -euo pipefail\n'
                        'if [ -f "$TMPDIR/date-called" ]; then echo 101; exit 9; fi\n'
                        'touch "$TMPDIR/date-called"\necho 100\n')
        result, outputs = self.run_probe()
        self.assertEqual(9, result.returncode)
        self.assertIn("status=passed\n", Path(self.env["GITHUB_OUTPUT"]).read_text())
        self.assertEqual("failed", outputs["status"])
        values = {**self.passing_values(), "steps.test5.outcome": "failure"}
        result, outputs = self.run_script(self.steps["summary"]["run"], values)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("1", outputs["core_failed"])
        self.assertEqual("failure", outputs["overall_status"])

    def test_summary_requires_passed_output_and_successful_outcome(self):
        values = self.passing_values()
        result, outputs = self.run_script(self.steps["summary"]["run"], values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", outputs["passed"])
        for i in range(1, 7):
            for field, value in (("outputs.status", ""), ("outputs.status", "failed"),
                                 ("outputs.status", "skipped"), ("outputs.status", "invalid"),
                                 ("outcome", "failure"), ("outcome", "cancelled"),
                                 ("outcome", "skipped"), ("outcome", "")):
                with self.subTest(i=i, field=field, value=value):
                    changed = {**values, f"steps.test{i}.{field}": value,
                               f"steps.test{i}.conclusion": "success"}
                    result, outputs = self.run_script(self.steps["summary"]["run"], changed)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", outputs["passed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual(str(int(i < 6)), outputs["core_failed"])
                    self.assertEqual("failing" if i < 6 else "passing", outputs["badge_status"])
                    self.assertEqual("failure", outputs["overall_status"])
        result, outputs = self.run_script(self.steps["summary"]["run"])
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("6", outputs["failed"])
        self.assertEqual("5", outputs["core_failed"])
        self.assertEqual("0", outputs["skipped"])

    def test_only_successful_no_newer_candidate_skip_is_allowed(self):
        for decision in ("", "no_newer_stable_available", "not_configured",
                         "runtime_validation_not_automated", "not_applicable_package_manager"):
            for outcome in ("success", "failure", "skipped", "cancelled", ""):
                with self.subTest(decision=decision, outcome=outcome):
                    values = {**self.passing_values(), "steps.test6.outputs.status": "skipped",
                              "steps.test6.outputs.decision": decision, "steps.test6.outcome": outcome}
                    result, outputs = self.run_script(self.steps["summary"]["run"], values)
                    accepted = decision == "no_newer_stable_available" and outcome == "success"
                    self.assertEqual(accepted, result.returncode == 0)
                    self.assertEqual(str(int(accepted)), outputs["skipped"])
                    self.assertEqual(str(int(not accepted)), outputs["failed"])
                    self.assertEqual("0", outputs["core_failed"])


if __name__ == "__main__":
    unittest.main()
