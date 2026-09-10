"""Run Mesa workflow shells against isolated identity and failure fixtures.

These fixtures test rejection/accounting behavior, not native Mesa support.
The deterministic model must also be exercised with the real PyPI installation.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-mesa.yml"
sys.path.insert(0, str(ROOT / ".github/scripts"))
import package_observation_migration_audit as audit
from package_result_policy import expected_regression_metadata

BASH = shutil.which("bash")
VERSION = "3.5.1"


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


class MesaWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = yaml.safe_load(WORKFLOW.read_text())
        cls.job = cls.document["jobs"]["test-mesa"]
        cls.steps = {step["id"]: step for step in cls.job["steps"] if "id" in step}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mesa-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        venv.EnvBuilder(with_pip=False).create(self.root / "runtime")
        self.python = self.root / "runtime/bin/python"
        self.site = Path(subprocess.check_output(
            [str(self.python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True,
        ).strip())
        self.module = self.site / "mesa"
        self.module.mkdir()
        self.module.joinpath("__init__.py").write_text(
            f'__version__ = "{VERSION}"\nfrom .model import Model\nfrom .agent import Agent\n'
        )
        # Only identity is represented; these classes cannot pass the model smoke.
        self.module.joinpath("model.py").write_text("class Model:\n    pass\n")
        self.module.joinpath("agent.py").write_text("class Agent:\n    pass\n")
        self.dist = self.site / f"mesa-{VERSION}.dist-info"
        self.dist.mkdir()
        self.metadata()
        self.dist.joinpath("RECORD").write_text(
            "mesa/__init__.py,,\nmesa/model.py,,\nmesa/agent.py,,\n"
        )
        self.dist.joinpath("INSTALLER").write_text("pip\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for command in ("date", "uname"):
            self.bin.joinpath(command).symlink_to(shutil.which(command))
        timeout = shutil.which("timeout") or shutil.which("gtimeout")
        if timeout:
            self.bin.joinpath("timeout").symlink_to(timeout)
        else:
            self.stub("timeout", "shift 2\nexec \"$@\"\n")
        self.output = self.root / "output"

    def stub(self, command, body):
        path = self.bin / command
        path.unlink(missing_ok=True)
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def metadata(self, version=VERSION, name="mesa"):
        self.dist.joinpath("METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        )

    def values(self):
        return {"steps.install.outputs.install_status": "success",
                "steps.version.outputs.status": "passed",
                "steps.version.outputs.version": VERSION}

    def run_step(self, name, values=None, source=None, **environment):
        values = self.values() if values is None else values
        step = self.steps[name]
        env = dict(os.environ, PATH=str(self.bin), GITHUB_OUTPUT=str(self.output),
                   MESA_PYTHON=str(self.python), PYTHONDONTWRITEBYTECODE="1")
        env.update({key: render(value, values) for key, value in step.get("env", {}).items()})
        env.update(environment)
        self.output.write_text("")
        result = subprocess.run(
            [BASH, "-e", "-o", "pipefail", "-c", render(source or step["run"], values)],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=15,
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

    def test_reusable_six_id_contract_and_bounds_are_preserved(self):
        self.assertEqual([key for key in self.steps if re.fullmatch(r"test\d+", key)],
                         [f"test{i}" for i in range(1, 7)])
        call = self.document.get("on", self.document.get(True))["workflow_call"]
        self.assertEqual(set(call["outputs"]), set(self.job["outputs"]))
        self.assertEqual(self.job["outputs"]["contract_version"], "2.0")
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        self.assertEqual(self.job["timeout-minutes"], 15)
        source = self.steps["install"]["run"]
        self.assertIn("--index-url https://pypi.org/simple", source)
        self.assertIn("--only-binary=:all:", source)
        self.assertIn("--retries 2 --timeout 30 'mesa[network]'", source)
        self.assertIn("timeout --kill-after=10s 300s", source)
        self.assertNotRegex(WORKFLOW.read_text(), r"mesa-utils|glxinfo|glxgears")

    def test_actual_auditor_sees_every_required_output(self):
        outputs = {"version": ("version", "status", "duration"),
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
        self.assertIn("baseline_failed", audit._step_literal_outputs(ROOT, self.steps["test6"], "decision"))

    def test_metadata_uses_canonical_dashboard_route(self):
        result, fields = self.run_step("metadata")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["package_slug"], "mesa")
        self.assertEqual(fields["dashboard_link"], "/linux/opensource_packages/mesa")

    def test_finalizers_are_explicit_and_tests_run_after_prerequisite_failure(self):
        for name in ("install", "version", "test1", "test2", "test3", "test4", "test5"):
            source = self.steps[name]["run"]
            self.assertIn('trap \'finish "$?"\' EXIT', source)
            self.assertTrue(source.rstrip().endswith("finish 0"))
            if name != "install":
                self.assertEqual(self.steps[name]["if"], "always()")

    def test_owned_distribution_and_import_versions_are_bound(self):
        for name in ("version", "test2"):
            result, fields = self.run_step(name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fields["version"], VERSION)
            self.assertEqual(fields["status"], "passed")
            self.assertTrue(fields["duration"].isdigit())
            if name == "test2":
                self.assertEqual(fields["installed_version"], VERSION)

    def test_identity_uses_isolated_python_and_ignores_path_shadow(self):
        shadow = self.root / "shadow"
        shadow.mkdir()
        shadow.joinpath("mesa.py").write_text("raise RuntimeError('foreign Mesa')\n")
        result, fields = self.run_step("version", PYTHONPATH=str(shadow), PYTHONOPTIMIZE="2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["version"], VERSION)

    def test_wrong_distribution_name_is_rejected(self):
        self.metadata(name="mesa-utils")
        for name in ("version", "test2"):
            self.rejected(name)

    def test_missing_package_or_distribution_is_rejected(self):
        shutil.rmtree(self.module)
        self.rejected("version")
        shutil.rmtree(self.dist)
        self.rejected("test2")

    def test_missing_or_incomplete_ownership_records_are_rejected(self):
        for records in ("", "mesa/__init__.py,,\n", "mesa/model.py,,\nmesa/agent.py,,\n"):
            with self.subTest(records=records):
                self.dist.joinpath("RECORD").write_text(records)
                for name in ("version", "test2"):
                    self.rejected(name)
        self.dist.joinpath("RECORD").unlink()
        self.rejected("version")

    def test_foreign_import_with_matching_version_is_rejected(self):
        foreign = self.root / "foreign.py"
        foreign.write_text("class Model:\n    pass\n")
        with self.module.joinpath("__init__.py").open("a") as handle:
            handle.write(f"__file__ = {str(foreign)!r}\n")
        for name in ("version", "test2"):
            self.rejected(name)

    def test_foreign_model_class_is_rejected(self):
        self.site.joinpath("foreign.py").write_text("class Model:\n    pass\n")
        with self.module.joinpath("__init__.py").open("a") as handle:
            handle.write("from foreign import Model\n")
        self.rejected("version")

    def test_ambiguous_import_owner_is_rejected(self):
        other = self.site / "foreign-1.0.dist-info"
        other.mkdir()
        other.joinpath("METADATA").write_text("Name: foreign\nVersion: 1.0\n")
        other.joinpath("top_level.txt").write_text("mesa\n")
        for name in ("version", "test2"):
            self.rejected(name)

    def test_malformed_missing_and_placeholder_versions_are_rejected(self):
        for version in ("", "unknown", "Mesa", "3", "3.5.1 trailing", "3.5.$(true)"):
            with self.subTest(version=version):
                self.metadata(version=version)
                for name in ("version", "test2"):
                    self.rejected(name)
        self.dist.joinpath("METADATA").write_text("Metadata-Version: 2.1\nName: mesa\n")
        self.rejected("version")

    def test_import_distribution_version_mismatch_is_rejected(self):
        self.metadata(version="3.5.2")
        for name in ("version", "test2"):
            self.rejected(name)

    def test_absent_or_changed_baseline_is_rejected(self):
        for version in ("", "unknown", "3.5.2", "3.5.1\nstatus=passed"):
            with self.subTest(version=version):
                values = self.values()
                values["steps.version.outputs.version"] = version
                for name in ("test2", "test5"):
                    self.rejected(name, values=values)

    def test_import_stdout_cannot_inject_version_outputs(self):
        with self.module.joinpath("__init__.py").open("a") as handle:
            handle.write('print("status=passed")\n')
        for name in ("version", "test2"):
            self.rejected(name)

    def test_failed_install_or_version_cannot_pass_core_checks(self):
        for prerequisite in ("steps.install.outputs.install_status", "steps.version.outputs.status"):
            values = self.values()
            values[prerequisite] = "failed"
            for i in range(1, 6):
                with self.subTest(prerequisite=prerequisite, test=i):
                    self.rejected(f"test{i}", values=values)

    def test_missing_interpreter_reports_failure_and_duration(self):
        for name in ("version", "test1", "test2", "test3", "test4", "test5"):
            self.rejected(name, MESA_PYTHON="/nonexistent/mesa-python")

    def test_timeout_and_nonzero_exit_cannot_pass_or_export_version(self):
        for code in (1, 23, 124, 137):
            self.stub("timeout", f"exit {code}\n")
            for name in ("version", "test1", "test2", "test3", "test4", "test5"):
                with self.subTest(code=code, step=name):
                    self.rejected(name)

    def test_identity_only_fixture_cannot_pass_real_agent_api_check(self):
        result, _ = self.rejected("test1")
        self.assertIn("TypeError", result.stderr)

    def test_wrong_uname_architecture_is_rejected(self):
        self.stub("uname", 'printf "%s\\n" x86_64\n')
        for name in ("test4", "test5"):
            self.rejected(name)

    def test_dependency_check_failure_is_rejected(self):
        result, _ = self.rejected("test3")
        self.assertIn("No module named pip", result.stderr)

    def summary_values(self):
        values = self.values()
        values.update({f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)})
        values.update({f"steps.test{i}.outcome": "success" for i in range(1, 7)})
        values.update({"steps.test6.outputs.status": "skipped",
                       "steps.test6.outputs.decision": "not_applicable_package_manager"})
        return values

    def test_package_manager_skip_and_five_core_summary(self):
        result, fields = self.run_step("test6", values=self.summary_values())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["status"], "skipped")
        self.assertEqual(fields["decision"], "not_applicable_package_manager")
        self.assertEqual(fields["current_version"], VERSION)
        self.assertEqual(fields["next_installed_version"], "not_applicable")
        result, fields = self.run_step("summary", values=self.summary_values())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields, {"passed": "5", "failed": "0", "core_failed": "0",
                                 "skipped": "1", "duration": "0", "overall_status": "success",
                                 "badge_status": "passing"})

    def test_baseline_failure_skip_matches_unchanged_semantic_policy(self):
        cases = [("steps.install.outputs.install_status", "failed", "baseline_install_failed")]
        cases += [(f"steps.test{i}.{field}", value, "baseline_failed")
                  for i in range(1, 6)
                  for field, value in (("outcome", "failure"), ("outcome", ""),
                                       ("outputs.status", "failed"), ("outputs.status", ""))]
        for key, value, decision in cases:
            with self.subTest(key=key, value=value):
                values = self.summary_values()
                values[key] = value
                if key.startswith("steps.install"):
                    for i in range(1, 6):
                        values[f"steps.test{i}.outputs.status"] = "failed"
                result, regression = self.run_step("test6", values=values)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(regression["status"], "skipped")
                self.assertEqual(regression["decision"], decision)
                values.update({f"steps.test6.outputs.{key}": value for key, value in regression.items()})
                result, fields = self.run_step("summary", values=values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(fields["skipped"], "1")
                self.assertEqual(fields["badge_status"], "failing")
                policy = expected_regression_metadata(decision=decision, core_failed=int(fields["core_failed"]))
                self.assertEqual(policy["run_status"], fields["overall_status"])
                self.assertEqual(policy["status"], regression["status"])

    def test_contradictory_baseline_and_package_manager_decisions_fail_summary(self):
        for core_failed, decision in ((False, "baseline_failed"), (False, "baseline_install_failed"),
                                      (True, "not_applicable_package_manager")):
            with self.subTest(core_failed=core_failed, decision=decision):
                values = self.summary_values()
                values["steps.test6.outputs.decision"] = decision
                if core_failed:
                    values["steps.test5.outputs.status"] = "failed"
                result, fields = self.run_step("summary", values=values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(fields["skipped"], "0")
                self.assertEqual(fields["badge_status"], "failing")

    def test_every_bad_or_missing_core_status_and_outcome_fails_summary(self):
        for i in range(1, 6):
            cases = [("outputs.status", status) for status in ("", "failed", "skipped")]
            cases += [("outcome", outcome) for outcome in ("", "failure", "cancelled", "skipped")]
            for field, value in cases:
                with self.subTest(test=i, field=field, value=value):
                    values = self.summary_values()
                    values[f"steps.test{i}.{field}"] = value
                    values["steps.test6.outputs.decision"] = "baseline_failed"
                    result, fields = self.run_step("summary", values=values)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(fields["passed"], "4")
                    self.assertEqual(fields["failed"], "1")
                    self.assertEqual(fields["core_failed"], "1")
                    self.assertEqual(fields["skipped"], "1")
                    self.assertEqual(fields["overall_status"], "failure")
                    self.assertEqual(fields["badge_status"], "failing")

    def test_skip_requires_successful_outcome_and_exact_semantic_decision(self):
        cases = [("outcome", outcome) for outcome in ("", "failure", "cancelled", "skipped")]
        cases += [("outputs.status", status) for status in ("", "passed", "failed")]
        cases += [("outputs.decision", decision) for decision in ("", "not_configured", "metadata_review_required")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                values = self.summary_values()
                values[f"steps.test6.{field}"] = value
                result, fields = self.run_step("summary", values=values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(fields["passed"], "5")
                self.assertEqual(fields["failed"], "1")
                self.assertEqual(fields["core_failed"], "0")
                self.assertEqual(fields["skipped"], "0")
                self.assertEqual(fields["badge_status"], "failing")

    def test_failed_summary_retains_all_six_durations(self):
        values = self.summary_values()
        values.update({f"steps.test{i}.outputs.duration": str(i) for i in range(1, 7)})
        values["steps.test5.outcome"] = "failure"
        result, fields = self.run_step("summary", values=values)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(fields["duration"], "21")


if __name__ == "__main__":
    unittest.main()
