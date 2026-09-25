"""Execute Vue workflow shells; real runtime tests need VUE_TEST_DIR.

Contract fixtures verify failure propagation, not product or Arm support.
The native evidence replay runs the runtime tests against the npm installation.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import package_observation_migration_audit as audit
from package_result_policy import expected_regression_metadata

BASH = shutil.which("bash")


def render(source, values):
    def expression(match):
        for term in match[1].split("||"):
            term = term.strip()
            value = term[1:-1] if term.startswith("'") else values.get(term, "")
            if term.isdigit():
                value = term
            if value:
                return str(value)
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)


class WorkflowShellMixin:
    """Shared shell contract checks for these two package-manager workflows."""

    @classmethod
    def setUpClass(cls):
        cls.workflow = ROOT / f".github/workflows/test-{cls.slug}.yml"
        cls.document = yaml.safe_load(cls.workflow.read_text())
        cls.job = cls.document["jobs"][f"test-{cls.slug}"]
        cls.steps = {step["id"]: step for step in cls.job["steps"] if "id" in step}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix=f"{self.slug}-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("date", "uname", "node"):
            if shutil.which(name):
                self.bin.joinpath(name).symlink_to(shutil.which(name))
        timeout = shutil.which("timeout") or shutil.which("gtimeout")
        if timeout:
            self.bin.joinpath("timeout").symlink_to(timeout)
        else:
            self.stub("timeout", 'shift 2\nexec "$@"\n')
        self.output = self.root / "output"
        self.runtime_env = {"VUE_DIR": str(self.root / "missing"),
                            "OPENMETRICS_PYTHON": str(self.root / "missing-python")}

    def stub(self, name, body):
        target = self.bin / name
        target.unlink(missing_ok=True)
        target.write_text("#!/bin/sh\n" + body)
        target.chmod(0o755)

    def values(self):
        return {"steps.install.outputs.install_status": "success",
                "steps.version.outputs.status": "passed",
                "steps.version.outputs.version": "1.0.0" if self.slug == "openmetrics" else "3.5.0",
                "steps.version.outputs.implementation_version": "0.26.0"}

    def run_step(self, name, values=None, source=None, **environment):
        values = self.values() if values is None else values
        step = self.steps[name]
        env = dict(os.environ, PATH=str(self.bin), GITHUB_OUTPUT=str(self.output),
                   GITHUB_ENV=str(self.root / "env"), RUNNER_TEMP=str(self.root),
                   PYTHONDONTWRITEBYTECODE="1")
        env.update(self.runtime_env)
        env.update({key: render(value, values) for key, value in step.get("env", {}).items()})
        env.update(environment)
        self.output.write_text("")
        result = subprocess.run(
            [BASH, "-e", "-o", "pipefail", "-c", render(source or step["run"], values)],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=45,
        )
        lines = self.output.read_text().splitlines()
        fields = dict(line.split("=", 1) for line in lines)
        self.assertEqual(len(lines), len(fields), "Duplicate output keys")
        return result, fields

    def rejected(self, name, **arguments):
        result, fields = self.run_step(name, **arguments)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(fields.get("status"), "failed")
        self.assertTrue(fields.get("duration", "").isdigit(), fields)
        self.assertNotIn("version", fields)
        self.assertNotIn("installed_version", fields)
        return result, fields

    def summary_values(self):
        values = self.values()
        values.update({f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)})
        values.update({f"steps.test{i}.outcome": "success" for i in range(1, 7)})
        values.update({"steps.test6.outputs.status": "skipped",
                       "steps.test6.outputs.decision": "not_applicable_package_manager"})
        return values

class WorkflowContractMixin(WorkflowShellMixin):
    def test_contract_and_finalizers(self):
        self.assertEqual([key for key in self.steps if re.fullmatch(r"test\d+", key)],
                         [f"test{i}" for i in range(1, 7)])
        call = self.document.get("on", self.document.get(True))["workflow_call"]
        self.assertEqual(set(call["outputs"]), set(self.job["outputs"]))
        self.assertEqual(self.job["outputs"]["contract_version"], "2.0")
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        self.assertEqual(self.job["timeout-minutes"], 15)
        for name in ("install", "version", "test1", "test2", "test3", "test4", "test5"):
            source = self.steps[name]["run"]
            self.assertIn('trap \'finish "$?"\' EXIT', source)
            self.assertTrue(source.rstrip().endswith("finish 0"))
            if name != "install":
                self.assertEqual(self.steps[name]["if"], "always()")

    def test_actual_auditor_recognizes_all_outputs(self):
        outputs = {"install": ("install_status", "duration"),
                   "version": ("version", "status", "duration"),
                   "test2": ("installed_version", "status", "duration"),
                   "test6": ("current_version", "latest_version", "next_installed_version",
                             "decision", "regression_result", "comparison", "status", "duration"),
                   "summary": ("passed", "failed", "core_failed", "skipped", "duration",
                               "overall_status", "badge_status")}
        outputs.update({f"test{i}": ("status", "duration") for i in (1, 3, 4, 5)})
        for name, fields in outputs.items():
            for field in fields:
                with self.subTest(step=name, field=field):
                    self.assertTrue(audit._step_emits_output(ROOT, self.steps[name], field))
        self.assertEqual(set(audit._step_literal_outputs(ROOT, self.steps["test6"], "decision")),
                         {"baseline_failed", "baseline_install_failed", "not_applicable_package_manager"})

    def test_metadata_route(self):
        result, fields = self.run_step("metadata")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["dashboard_link"], f"/linux/opensource_packages/{self.slug}")

    def test_failed_prerequisites_fail_all_core_steps(self):
        for prerequisite in ("steps.install.outputs.install_status", "steps.version.outputs.status"):
            for state in ("", "failed"):
                values = self.values()
                values[prerequisite] = state
                for i in range(1, 6):
                    with self.subTest(prerequisite=prerequisite, state=state, step=i):
                        self.rejected(f"test{i}", values=values)

    def test_missing_runtime_cannot_pass(self):
        self.stub("node", "exit 127\n")
        for name in ("version", "test1", "test2", "test3", "test4", "test5"):
            self.rejected(name)

    def test_command_failure_or_timeout_cannot_pass(self):
        for code in (1, 23, 124, 137):
            self.stub("timeout", f"exit {code}\n")
            self.stub("uname", 'printf "aarch64\\n"\n')
            for name in ("version", "test1", "test2", "test3", "test4", "test5"):
                with self.subTest(code=code, step=name):
                    self.rejected(name, VUE_DIR=str(self.root))

    def test_five_core_passes_and_one_skip(self):
        values = self.summary_values()
        result, fields = self.run_step("test6", values=values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["status"], "skipped")
        self.assertEqual(fields["decision"], "not_applicable_package_manager")
        self.assertEqual(fields["current_version"], values["steps.version.outputs.version"])
        values.update({f"steps.test6.outputs.{key}": value for key, value in fields.items()})
        result, fields = self.run_step("summary", values=values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields, {"passed": "5", "failed": "0", "core_failed": "0", "skipped": "1",
                                 "duration": "0", "overall_status": "success", "badge_status": "passing"})

    def test_every_bad_status_and_outcome_is_counted(self):
        for i in range(1, 6):
            cases = [("outputs.status", state) for state in ("", "failed", "skipped")]
            cases += [("outcome", state) for state in ("", "failure", "cancelled", "skipped")]
            for field, value in cases:
                with self.subTest(step=i, field=field, value=value):
                    values = self.summary_values()
                    values[f"steps.test{i}.{field}"] = value
                    result, skip = self.run_step("test6", values=values)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(skip["decision"], "baseline_failed")
                    values.update({f"steps.test6.outputs.{key}": value for key, value in skip.items()})
                    result, fields = self.run_step("summary", values=values)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual((fields["passed"], fields["failed"], fields["core_failed"], fields["skipped"]),
                                     ("4", "1", "1", "1"))
                    policy = expected_regression_metadata(decision=skip["decision"], core_failed=1)
                    self.assertEqual(fields["overall_status"], policy["run_status"])
                    self.assertEqual(skip["status"], policy["status"])

    def test_install_failure_and_skip_accounting(self):
        values = self.summary_values()
        values["steps.install.outputs.install_status"] = "failed"
        for i in range(1, 6):
            values[f"steps.test{i}.outputs.status"] = "failed"
        result, skip = self.run_step("test6", values=values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(skip["decision"], "baseline_install_failed")
        values.update({f"steps.test6.outputs.{key}": value for key, value in skip.items()})
        result, fields = self.run_step("summary", values=values)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((fields["passed"], fields["failed"], fields["skipped"]), ("0", "5", "1"))

    def test_invalid_skip_never_passes(self):
        cases = [("outcome", state) for state in ("", "failure", "cancelled", "skipped")]
        cases += [("outputs.status", state) for state in ("", "passed", "failed")]
        cases += [("outputs.decision", state) for state in ("", "not_configured", "baseline_failed", "baseline_install_failed")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                values = self.summary_values()
                values[f"steps.test6.{field}"] = value
                result, fields = self.run_step("summary", values=values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((fields["passed"], fields["failed"], fields["skipped"]), ("5", "1", "0"))
                self.assertEqual(fields["badge_status"], "failing")

    def test_duration_survives_failure(self):
        values = self.summary_values()
        values.update({f"steps.test{i}.outputs.duration": str(i) for i in range(1, 7)})
        values["steps.test5.outcome"] = "failure"
        values["steps.test6.outputs.decision"] = "baseline_failed"
        result, fields = self.run_step("summary", values=values)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(fields["duration"], "21")


class VueWorkflowTests(WorkflowContractMixin, unittest.TestCase):
    slug = "vue"

    def test_cli_cannot_supply_framework_identity(self):
        self.stub("vue", 'printf "@vue/cli 5.0.9\\n"\n')
        self.rejected("version", VUE_DIR=str(self.root))
        self.assertNotIn("@vue/cli", self.steps["install"]["run"])


@unittest.skipUnless(os.environ.get("VUE_TEST_DIR"), "Real npm Vue installation requires VUE_TEST_DIR")
class VueRuntimeTests(WorkflowShellMixin, unittest.TestCase):
    slug = "vue"

    def real(self, name, **arguments):
        return self.run_step(name, VUE_DIR=os.environ["VUE_TEST_DIR"], **arguments)

    def baseline(self):
        result, fields = self.real("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        values = self.values()
        values["steps.version.outputs.version"] = fields["version"]
        return values

    def test_real_identity_reactivity_and_ssr(self):
        values = self.baseline()
        for name in ("test1", "test2", "test3", "test5"):
            result, fields = self.real(name, values=values)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fields["status"], "passed")

    def test_changed_framework_version_fails(self):
        values = self.baseline()
        values["steps.version.outputs.version"] = "5.0.9"
        for name in ("test2", "test5"):
            self.rejected(name, values=values, VUE_DIR=os.environ["VUE_TEST_DIR"])

    def test_real_reactivity_and_ssr_mutations_fail(self):
        values = self.baseline()
        mutations = [("test3", "state.count = 5;", "state.count = 6;"),
                     ("test3", "stop();", "/* watcher remains active */"),
                     ("test5", "state.count = 5;", "state.count = 6;"),
                     ("test5", "props.label + ': ' + props.value", "props.value"),
                     ("test5", "const before = await render();", "throw new Error('SSR rejected');")]
        for name, before, after in mutations:
            with self.subTest(step=name, mutation=before):
                source = self.steps[name]["run"]
                self.assertIn(before, source)
                self.rejected(name, values=values, source=source.replace(before, after),
                              VUE_DIR=os.environ["VUE_TEST_DIR"])


if __name__ == "__main__":
    unittest.main()
