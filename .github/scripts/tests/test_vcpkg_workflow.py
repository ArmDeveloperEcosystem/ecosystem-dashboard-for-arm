"""Focused package workflow regression checks."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-vcpkg.yml"


class VcpkgWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="vcpkg-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-vcpkg"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.env = dict(os.environ, **self.job["env"], GITHUB_OUTPUT=str(self.root / "output"),
                        TMPDIR=str(self.root), RUNNER_TEMP=str(self.root))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        self.values = {"steps.install.outputs.install_mode": "github_source",
                       "steps.install.outputs.install_status": "success"}

    def stub(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + script)
        path.chmod(0o755)

    def run_step(self, step_id, values=None, **env):
        values = {**self.values, **(values or {})}
        def expression(match):
            for part in match[1].split("||"):
                key = part.strip()
                value = (key[1:-1] if key.startswith("'") else
                         self.env.get(key[4:]) if key.startswith("env.") else values.get(key))
                if value:
                    return str(value)
            return ""
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step_id]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=20)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def passing_values(self):
        return {key: value for i in range(1, 7) for key, value in (
            (f"steps.test{i}.outputs.status", "passed"), (f"steps.test{i}.outcome", "success"))}

    def test_summary_requires_passed_output_and_successful_outcome(self):
        values = self.passing_values()
        result, outputs = self.run_step("summary", values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", outputs["passed"])
        for i in range(1, 7):
            for field, value in (("outputs.status", ""), ("outputs.status", "failed"),
                                 ("outputs.status", "skipped"), ("outcome", "failure"),
                                 ("outcome", "cancelled"), ("outcome", "skipped"), ("outcome", "")):
                with self.subTest(i=i, field=field, value=value):
                    changed = {**values, f"steps.test{i}.{field}": value,
                               f"steps.test{i}.conclusion": "success"}
                    result, outputs = self.run_step("summary", changed)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", outputs["passed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual(str(int(i < 6)), outputs["core_failed"])
                    self.assertEqual("failure", outputs["overall_status"])
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("6", outputs["failed"])
        self.assertEqual("5", outputs["core_failed"])

    def test_only_explicit_successful_regression_skip_is_allowed(self):
        values = self.passing_values()
        values["steps.test6.outputs.status"] = "skipped"
        allowed = "not_applicable_package_manager"
        for decision in ("not_configured", "runtime_validation_not_automated",
                         "metadata_review_required", "no_newer_stable_available",
                         "not_applicable_package_manager"):
            for outcome in ("success", "failure", "cancelled", ""):
                with self.subTest(decision=decision, outcome=outcome):
                    values.update({"steps.test6.outputs.decision": decision,
                                   "steps.test6.outcome": outcome})
                    result, outputs = self.run_step("summary", values)
                    accepted = decision == allowed and outcome == "success"
                    self.assertEqual(accepted, result.returncode == 0)
                    self.assertEqual(str(int(accepted)), outputs["skipped"])
                    self.assertEqual(str(int(not accepted)), outputs["failed"])
                    self.assertEqual("0", outputs["core_failed"])

    def prepare_source(self):
        import json
        source = self.root / "baseline-src/vcpkg-artifacts"
        source.mkdir(parents=True)
        self.manifest = source / "package.json"
        self.identity = {"name": "@microsoft/vcpkg-ce", "author": "Microsoft",
                         "description": "vcpkg-artifacts",
                         "repository": {"type": "git", "url": "git+https://github.com/Microsoft/vcpkg-tool.git"},
                         "keywords": ["vcpkg", "vcpkg-artifacts"]}
        self.manifest.write_text(json.dumps(self.identity))
        self.values.update({"steps.expectations.outputs.identity_kind": "package_json_name",
                            "steps.expectations.outputs.identity_target": "vcpkg-artifacts/package.json",
                            "steps.expectations.outputs.identity_expect": "@microsoft/vcpkg-ce",
                            "steps.expectations.outputs.external_expect": "vcpkg"})

    def test_same_release_structured_microsoft_identity_passes(self):
        self.prepare_source()
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertIn("2025.04.09 / tool 2025-04-07", outputs["note"])

    def test_missing_name_wrong_vendor_and_wrong_repository_fail(self):
        import json
        self.prepare_source()
        for field, value in (("name", None), ("name", "vcpkg"), ("author", "Other"),
                             ("description", "unrelated"), ("repository", None),
                             ("repository", {"type": "git", "url": "https://example.com/vcpkg"}),
                             ("keywords", []), ("keywords", "vcpkg vcpkg-artifacts")):
            with self.subTest(field=field, value=value):
                self.manifest.write_text(json.dumps({**self.identity, field: value}))
                result, outputs = self.run_step("test5", {"steps.expectations.outputs.identity_expect": "wrong-project"})
                self.assertNotEqual(0, result.returncode)
                self.assertNotEqual("passed", outputs.get("status"))
        self.manifest.write_text("{")
        result, outputs = self.run_step("test5")
        self.assertNotEqual(0, result.returncode)
        self.manifest.unlink()
        result, outputs = self.run_step("test5")
        self.assertNotEqual(0, result.returncode)

    def test_install_requires_registry_mapping_and_exact_tool_commit(self):
        self.env.update(FETCH_EXIT="0", CLONE_EXIT="0", TOOL_TAG="2025-04-07",
                        SOURCE_COMMIT="b8b513ba8778c918cff49c3e837aae5999d5d2aa")
        self.stub("curl", '''
if [ "$FETCH_EXIT" != 0 ]; then exit "$FETCH_EXIT"; fi
printf 'VCPKG_TOOL_RELEASE_TAG=%s\\n' "$TOOL_TAG" > baseline-external/tool-metadata.txt
''')
        self.stub("git", '''
if [ "$1" = clone ]; then
  test "$4" = --branch && test "$5" = 2025-04-07
  test "$6" = https://github.com/microsoft/vcpkg-tool.git
  if [ "$CLONE_EXIT" != 0 ]; then exit "$CLONE_EXIT"; fi
  mkdir baseline-src
else
  test "$1" = -C && test "$3" = rev-parse && test "$4" = HEAD
  echo "$SOURCE_COMMIT"
fi
''')
        result, outputs = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("success", outputs["install_status"])
        self.assertEqual("2025-04-07", outputs["resolved_tag"])
        self.assertEqual("2025.04.09", outputs["registry_release"])
        self.assertEqual("25.04.09", self.env["BASELINE_VERSION"])
        for env in ({"BASELINE_REGISTRY_TAG": "2025.04.16"}, {"TOOL_TAG": "2025-04-16"},
                    {"FETCH_EXIT": "22"}, {"CLONE_EXIT": "128"}, {"SOURCE_COMMIT": "a" * 40}):
            with self.subTest(env=env):
                result, outputs = self.run_step("install", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertNotEqual("success", outputs.get("install_status"))


if __name__ == "__main__":
    unittest.main()

