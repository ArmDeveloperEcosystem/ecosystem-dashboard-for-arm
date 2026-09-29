"""Execute the Krb5 workflow's version and summary shell with controlled CLIs."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

from test_guacamole_workflow import PMDecisionChecks


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-krb5.yml"
BANNER = "Kerberos 5 version "
VERSION = "1.20.1"
PACKAGE_VERSION = "1.20.1-6ubuntu2.6"


class Krb5WorkflowTests(PMDecisionChecks, unittest.TestCase):
    workflow_path = WORKFLOW

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="krb5-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-krb5"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, executable in (("python3", sys.executable), ("date", shutil.which("date"))):
            (self.bin / name).symlink_to(executable)
        self.env = dict(os.environ, PATH=str(self.bin), PYTHONDONTWRITEBYTECODE="1",
                        GITHUB_OUTPUT=str(self.root / "output"),
                        CLI_STDOUT=BANNER + VERSION + "\n", CLI_STDERR="", CLI_RC="0",
                        PM_OUTPUT=self.package_row(), PM_RC="0", FILES_RC="0",
                        PM_FILES=str(self.bin / "klist") + "\n")
        self.stub("klist", """
test "$#" = 1
test "$1" = -V
test "$LC_ALL" = C
printf '%s' "$CLI_STDOUT"
printf '%s' "$CLI_STDERR" >&2
exit "$CLI_RC"
""")
        self.stub("dpkg-query", r"""
case "$1" in
  -W)
    test "$#" = 3
    test "$2" = $'-f=${Package}\t${Status}\t${Version}\t${Architecture}\t${source:Upstream-Version}\n'
    test "$3" = krb5-user
    printf '%s' "$PM_OUTPUT"
    exit "$PM_RC"
    ;;
  -L)
    test "$#" = 2
    test "$2" = krb5-user
    printf '%s' "$PM_FILES"
    exit "$FILES_RC"
    ;;
  *) exit 99 ;;
esac
""")

    def package_row(self, version=VERSION, package_version=PACKAGE_VERSION):
        return f"krb5-user\tinstall ok installed\t{package_version}\tarm64\t{version}\n"

    def stub(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + script)
        path.chmod(0o755)

    def run_step(self, name, values=None, **env):
        values = values or {}

        def render(text):
            def expression(match):
                for term in match[1].split("||"):
                    term = term.strip()
                    if term.startswith("'") and term.endswith("'"):
                        return term[1:-1]
                    if term.isdigit():
                        return term
                    if values.get(term):
                        return str(values[term])
                return ""
            return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, text)

        step = self.steps[name]
        step_env = {key: render(value) for key, value in step.get("env", {}).items()}
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["/bin/bash", "-e", "-c", render(step["run"])],
                                cwd=self.root, env={**self.env, **step_env, **env},
                                capture_output=True, text=True, timeout=15)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(line) == 2 for line in lines), lines)
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        return result, outputs

    def verified(self, version=VERSION):
        return {"steps.version.outputs.version": version,
                "steps.version.outputs.status": "passed"}

    def assert_rejected(self, name="version", values=None, **env):
        result, outputs = self.run_step(name, values or self.verified(), **env)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs.get("status"), "failed")
        self.assertNotIn("version", outputs)
        self.assertNotIn("package_version", outputs)
        if name == "test3":
            self.assertRegex(outputs["duration"], r"^[0-9]+$")
        return outputs

    def test_successful_cli_is_bound_to_installed_package(self):
        for version, package_version in ((VERSION, PACKAGE_VERSION),
                                         ("9.12.3", "2:9.12.3-4+b1"),
                                         ("9.12", "9.12-1ubuntu1")):
            with self.subTest(version=version):
                result, outputs = self.run_step(
                    "version", CLI_STDOUT=BANNER + version + "\n",
                    PM_OUTPUT=self.package_row(version, package_version))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(outputs, {"version": version, "package_version": package_version,
                                           "status": "passed"})

    def test_single_banner_on_stderr_is_valid_after_successful_exit(self):
        result, outputs = self.run_step("version", CLI_STDOUT="",
                                        CLI_STDERR=BANNER + VERSION + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["version"], VERSION)

    def test_malformed_wrong_product_duplicate_and_missing_banners(self):
        valid = BANNER + VERSION + "\n"
        for banner in ("", "Kerberos\n", "(guacd)\n", "Heimdal 5 version 1.20.1\n",
                       BANNER + "unknown\n", BANNER + "1.x.3\n",
                       "prefix " + valid, valid.rstrip() + " suffix\n",
                       valid + valid, "\n" + valid, valid + "\n",
                       "Usage: klist\n" + valid, valid + "status=passed\n"):
            with self.subTest(banner=banner):
                self.assert_rejected(CLI_STDOUT=banner)

    def test_nonzero_cli_never_publishes_a_version(self):
        for code in ("1", "2", "127", "139"):
            with self.subTest(code=code):
                self.assert_rejected(CLI_RC=code)

    def test_stderr_diagnostics_cannot_hide_behind_a_valid_banner(self):
        self.assert_rejected(CLI_STDERR="invalid option\n")

    def test_missing_executable_is_rejected(self):
        (self.bin / "klist").unlink()
        self.assert_rejected()
        self.assert_rejected("test3")

    def test_wrong_missing_duplicate_or_uninstalled_package_is_rejected(self):
        row = self.package_row()
        for package in ("", row + row, row.replace("krb5-user", "other-product"),
                        row.replace("install ok installed", "deinstall ok config-files"),
                        row.replace("arm64", "amd64"), row.replace(PACKAGE_VERSION, "unknown"),
                        row.replace("\t" + VERSION + "\n", "\t9.99.9\n")):
            with self.subTest(package=package):
                self.assert_rejected(PM_OUTPUT=package)

    def test_package_query_failure_is_rejected_even_with_valid_output(self):
        self.assert_rejected(PM_RC="1")
        self.assert_rejected(FILES_RC="1")

    def test_unowned_executable_is_rejected(self):
        self.assert_rejected(PM_FILES="/usr/local/bin/other\n")
        self.assert_rejected(PM_FILES="")

    def test_core_version_check_runs_real_command_and_matches_verified_version(self):
        result, outputs = self.run_step("test3", self.verified())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "passed")
        self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_core_version_check_rejects_invalid_changed_or_nonzero_output(self):
        valid = BANNER + VERSION + "\n"
        for banner in ("", BANNER + "9.99.9\n", "Heimdal 5 version 1.20.1\n",
                       valid + valid, valid + "\n", "Usage: klist\n" + valid):
            with self.subTest(banner=banner):
                self.assert_rejected("test3", CLI_STDOUT=banner)
        self.assert_rejected("test3", CLI_RC="1")
        self.assert_rejected("test3", CLI_STDERR="invalid option\n")

    def test_core_version_check_requires_verified_package_identity(self):
        for version in ("", "unknown", "(guacd)", "Kerberos", VERSION + "\n"):
            with self.subTest(version=version):
                self.assert_rejected("test3", self.verified(version))
        values = self.verified()
        values["steps.version.outputs.status"] = "failed"
        self.assert_rejected("test3", values)
        self.assertTrue(self.steps["version"]["continue-on-error"])

    def test_package_manager_regression_skip_and_success_summary(self):
        values = self.summary_values()
        result, regression = self.run_step("test6", values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(regression["status"], "skipped")
        self.assertEqual(regression["decision"], "not_applicable_package_manager")
        self.assertEqual(regression["current_version"], VERSION)
        values.update({f"steps.test6.outputs.{key}": value for key, value in regression.items()})
        result, outputs = self.run_step("summary", values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, {"passed": "5", "failed": "0", "core_failed": "0",
                                   "skipped": "1", "duration": "0",
                                   "overall_status": "success", "badge_status": "passing"})

    def test_core_failure_or_missing_status_has_consistent_summary(self):
        for status in ("failed", ""):
            with self.subTest(status=status):
                values = self.summary_values()
                values["steps.test3.outputs.status"] = status
                self.pm_guard(values)
                result, outputs = self.run_step("summary", values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["passed"], "4")
                self.assertEqual(outputs["failed"], "1")
                self.assertEqual(outputs["core_failed"], "1")
                self.assertEqual(outputs["skipped"], "1")
                self.assertEqual(outputs["overall_status"], "failure")
                self.assertEqual(outputs["badge_status"], "failing")


if __name__ == "__main__":
    unittest.main()
