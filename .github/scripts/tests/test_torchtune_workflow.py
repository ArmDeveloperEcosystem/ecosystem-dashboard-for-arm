"""Torchtune dependency pins, runtime checks, and install failure propagation."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-torchtune.yml"
EXPECTED = {
    "torch": "2.6.0",
    "torchvision": "0.21.0",
    "torchao": "0.10.0",
    "torchtune": "0.6.1",
    "tokenizers": "0.23.2",
    "huggingface-hub": "1.31.0",
}


class TorchtuneWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-torchtune"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        temporary = tempfile.TemporaryDirectory(prefix="torchtune-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        binary = self.root / "bin"
        binary.mkdir()
        helper = self.root / "fixture.py"
        helper.write_text('''
import importlib.metadata
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

args = sys.argv[1:]
with open(os.environ["FIXTURE_CALLS"], "a") as calls:
    calls.write(json.dumps(args) + "\\n")
if args[:2] == ["-m", "venv"]:
    target = Path(args[2]) / "bin"
    target.mkdir(parents=True, exist_ok=True)
    (target / "activate").write_text(":\\n")
    sys.exit(0)
if args[:3] == ["-m", "pip", "install"]:
    key = "FIXTURE_UPGRADE_RC" if "--upgrade" in args else "FIXTURE_INSTALL_RC"
    sys.exit(int(os.environ.get(key, "0")))
if args == ["-m", "pip", "check"]:
    sys.exit(int(os.environ.get("FIXTURE_CHECK_RC", "0")))
if os.environ.get("FIXTURE_IMPORT_FAIL"):
    sys.modules["torchtune"] = None
else:
    sys.modules["torchtune"] = SimpleNamespace(__version__="0.6.1")
if args[:1] == ["-c"]:
    exec(compile(args[1], "<workflow-command>", "exec"))
elif args == ["-"]:
    versions = json.loads(os.environ["FIXTURE_VERSIONS"])
    def version(package):
        if package not in versions:
            raise importlib.metadata.PackageNotFoundError(package)
        return versions[package]
    importlib.metadata.version = version
    recipes = ["fixture-recipe"] if not os.environ.get("FIXTURE_EMPTY_RECIPES") else []
    sys.modules["torchtune._recipe_registry"] = SimpleNamespace(get_all_recipes=lambda: recipes)
    exec(compile(sys.stdin.read(), "<workflow-probe>", "exec"))
else:
    raise AssertionError(args)
''')
        python = binary / "python3"
        python.write_text('#!/bin/sh\nexec "$FIXTURE_PYTHON" "$FIXTURE_HELPER" "$@"\n')
        python.chmod(0o755)
        runtime = self.root / "venv/bin"
        runtime.mkdir(parents=True)
        (runtime / "activate").write_text(":\n")
        self.env = {
            **os.environ, **self.job["env"],
            "PATH": str(binary) + os.pathsep + os.environ["PATH"],
            "VIRTUAL_ENV": str(runtime.parent),
            "GITHUB_OUTPUT": str(self.root / "output"),
            "GITHUB_PATH": str(self.root / "path"),
            "GITHUB_ENV": str(self.root / "env"),
            "FIXTURE_PYTHON": sys.executable,
            "FIXTURE_HELPER": str(helper),
            "FIXTURE_CALLS": str(self.root / "calls"),
            "FIXTURE_VERSIONS": json.dumps(EXPECTED),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def run_step(self, name, **environment):
        for key in ("GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_ENV", "FIXTURE_CALLS"):
            Path(self.env[key]).write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.steps[name]["run"]],
            cwd=self.root, env={**self.env, **environment},
            capture_output=True, text=True, timeout=15,
        )
        outputs = dict(line.split("=", 1) for line in
                       Path(self.env["GITHUB_OUTPUT"]).read_text().splitlines())
        return result, outputs

    def calls(self):
        return [json.loads(line) for line in Path(self.env["FIXTURE_CALLS"]).read_text().splitlines()]

    def test_install_keeps_baseline_and_compatible_hub_tokenizers_pins(self):
        result, outputs = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("success", outputs["install_status"])
        self.assertEqual([
            ["-m", "venv", "venv"],
            ["-m", "pip", "install", "--upgrade", "pip"],
            ["-m", "pip", "install", "--only-binary=tokenizers",
             *[f"{name}=={version}" for name, version in EXPECTED.items()]],
        ], self.calls())
        self.assertEqual(str(self.root / "venv/bin") + "\n",
                         Path(self.env["GITHUB_PATH"]).read_text())
        self.assertNotIn("continue-on-error", self.steps["install"])
        self.assertNotIn("RUSTFLAGS", WORKFLOW.read_text())
        self.assertNotIn("--no-deps", self.steps["install"]["run"])

    def test_failed_dependency_install_cannot_publish_success_or_environment(self):
        result, outputs = self.run_step("install", FIXTURE_INSTALL_RC="23")
        self.assertEqual(23, result.returncode, result.stderr)
        self.assertNotIn("install_status", outputs)
        self.assertEqual("", Path(self.env["GITHUB_PATH"]).read_text())
        self.assertEqual("", Path(self.env["GITHUB_ENV"]).read_text())

    def test_failed_pip_upgrade_stops_before_dependency_install(self):
        result, outputs = self.run_step("install", FIXTURE_UPGRADE_RC="19")
        self.assertEqual(19, result.returncode, result.stderr)
        self.assertNotIn("install_status", outputs)
        self.assertEqual(2, len(self.calls()))

    def test_metadata_requires_all_six_installed_versions_and_pip_check(self):
        result, outputs = self.run_step("test3")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertEqual([["-m", "pip", "check"], ["-"]], self.calls())
        for package, version in EXPECTED.items():
            self.assertIn(f"'{package}': '{version}'", result.stdout)

    def test_wrong_or_missing_dependency_versions_fail_metadata_check(self):
        for package in EXPECTED:
            for missing in (False, True):
                with self.subTest(package=package, missing=missing):
                    versions = dict(EXPECTED)
                    if missing:
                        del versions[package]
                    else:
                        versions[package] = "0.0.0"
                    result, outputs = self.run_step("test3", FIXTURE_VERSIONS=json.dumps(versions))
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", outputs["status"])

    def test_failed_pip_check_cannot_pass_or_run_metadata_probe(self):
        result, outputs = self.run_step("test3", FIXTURE_CHECK_RC="17")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertEqual([["-m", "pip", "check"]], self.calls())

    def test_runtime_import_and_version_checks_still_fail_on_import_error(self):
        for name in ("test1", "test2"):
            with self.subTest(step=name):
                result, outputs = self.run_step(name, FIXTURE_IMPORT_FAIL="1")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])

    def test_version_reporting_still_uses_runtime_version(self):
        result, outputs = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("0.6.1", outputs["version"])

    def test_recipe_runtime_check_rejects_empty_registry(self):
        for empty in ("", "1"):
            with self.subTest(empty=empty):
                result, outputs = self.run_step("test5", FIXTURE_EMPTY_RECIPES=empty)
                self.assertEqual(empty == "", result.returncode == 0, result.stderr)
                self.assertEqual("failed" if empty else "passed", outputs["status"])


if __name__ == "__main__":
    unittest.main()
