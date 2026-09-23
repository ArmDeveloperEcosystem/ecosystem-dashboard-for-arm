"""Offline execution fixtures for Xml2 workflow plumbing, not native Arm evidence."""

import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-xml2.yml"
# Frozen main 6aecd270b8d60ab7a1d9bf3ca570d0ca50f0848d, before the ten-line deletion.
ORIGINAL_SHA256 = "b478b2bc46c6bd723cb67f827b4008ef496da2bf6f0458de04f66cc40e866ace"
VERSION_SCRIPT = r'''set -euo pipefail
VERSION=$(Rscript -e '.libPaths(c(Sys.getenv("XML2_LIB"), Sys.getenv("XML2_USER_LIB"), .libPaths())); cat(as.character(packageVersion("xml2")))' | tr -d '\n' || echo "unknown")
echo "version=${VERSION}" >> "$GITHUB_OUTPUT"
'''
DEAD_LOOKUP = r'''LATEST=$(python3 - <<'PY'
import re
import urllib.request

text = urllib.request.urlopen("https://cloud.r-project.org/src/contrib/PACKAGES", timeout=20).read().decode()
match = re.search(r"Package: xml2\nVersion: ([^\n]+)", text)
print(match.group(1) if match else "unknown")
PY
)
'''
OLD_VERSION_SCRIPT = VERSION_SCRIPT.replace(
    'echo "version=${VERSION}"', DEAD_LOOKUP + 'echo "version=${VERSION}"'
) + 'echo "latest=${LATEST}" >> "$GITHUB_OUTPUT"\n'


class Xml2WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_bytes().decode("utf-8")
        self.workflow = yaml.load(self.source, Loader=yaml.BaseLoader)
        self.job = self.workflow["jobs"]["test-xml2"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        temporary = tempfile.TemporaryDirectory(prefix="xml2 workflow ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash)
        for command in ("date", "tr"):
            executable = shutil.which(command)
            self.assertIsNotNone(executable)
            (self.bin / command).symlink_to(executable)
        self.output = self.root / "output"
        self.network = self.root / "network-attempts"
        self.arguments = self.root / "rscript-arguments"
        self.env = {
            **os.environ, **self.job["env"], "PATH": str(self.bin),
            "HOME": str(self.root), "TMPDIR": str(self.root),
            "RUNNER_TEMP": str(self.root), "FIXTURE_ROOT": str(self.root),
            "GITHUB_OUTPUT": str(self.output), "PYTHONDONTWRITEBYTECODE": "1",
            "REPORTED_VERSION": "1.3.6", "RSCRIPT_EXIT": "0",
        }
        self.stub("Rscript", '''printf '%s\\n' "$@" >> "$FIXTURE_ROOT/rscript-arguments"
printf '%s' "$REPORTED_VERSION"
exit "$RSCRIPT_EXIT"
''')
        for command in ("python", "python3", "curl", "wget"):
            self.stub(command, f'''printf '%s\\n' '{command}' >> "$FIXTURE_ROOT/network-attempts"
printf '%s\\n' 'Forbidden command: {command}' >&2
exit 97
''')

    def stub(self, name, script):
        path = self.bin / name
        path.write_text(f"#!{self.bash}\nset -euo pipefail\n" + script)
        path.chmod(0o755)

    def run_step(self, name, values=None, source=None, **environment):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if (values or {}).get(term):
                    return str(values[term])
            return ""

        script = self.steps[name]["run"] if source is None else source
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        for path in (self.output, self.network, self.arguments):
            path.write_text("")
        result = subprocess.run(
            [self.bash, "-euo", "pipefail", "-c", script], cwd=self.root,
            env={**self.env, **environment}, capture_output=True, text=True, timeout=10,
        )
        pairs = [line.split("=", 1) for line in self.output.read_text().splitlines()]
        self.assertEqual(len(pairs), len(dict(pairs)), "duplicate step output")
        return result, dict(pairs)

    def core_values(self):
        return {f"steps.test{i}.outputs.{key}": value
                for i in range(1, 6) for key, value in (("status", "passed"), ("duration", "2"))}

    def test_exactly_ten_dead_lines_removed_and_all_other_workflow_bytes_unchanged(self):
        self.assertEqual(self.steps["version"]["run"], VERSION_SCRIPT)
        current = textwrap.indent(VERSION_SCRIPT, "          ")
        original = textwrap.indent(OLD_VERSION_SCRIPT, "          ")
        self.assertEqual(self.source.count(current), 1)
        restored = self.source.replace(current, original, 1).encode("utf-8")
        self.assertEqual(hashlib.sha256(restored).hexdigest(), ORIGINAL_SHA256)
        self.assertEqual(len(original.splitlines()) - len(current.splitlines()), 10)

    def test_pinned_install_and_all_five_real_core_checks_are_preserved(self):
        self.assertEqual(self.job["env"]["XML2_VERSION"], "1.3.6")
        self.assertIn('remotes::install_version(', self.steps["install"]["run"])
        self.assertIn('version = Sys.getenv("XML2_VERSION")', self.steps["install"]["run"])
        checks = {
            "test1": ('command -v R ', 'command -v Rscript ', '${XML2_LIB}/xml2/DESCRIPTION'),
            "test2": ('packageVersion("xml2")', '[ "${VERSION_OUTPUT}" = "${XML2_VERSION}" ]'),
            "test3": ('library(help = "xml2")', 'grep -qi "Information on package"'),
            "test4": ('*/xml2/libs/xml2.so', 'file "${LIB_PATH}"', "grep -qi 'aarch64'"),
            "test5": ('library(xml2)', 'read_xml(', 'read_html(', 'xml_find_first(doc, ".//item")',
                      'xml_find_first(html, ".//p")', 'stopifnot(node_text == "arm64")',
                      'stopifnot(html_text == "Hello")', "grep -q 'arm64 Hello'"),
        }
        for name, fragments in checks.items():
            with self.subTest(step=name):
                self.assertEqual(self.steps[name]["continue-on-error"], "true")
                for fragment in fragments:
                    self.assertIn(fragment, self.steps[name]["run"])
                self.assertIn('echo "status=failed"', self.steps[name]["run"])
                self.assertIn("exit 1", self.steps[name]["run"])

    def test_version_reports_installed_value_without_python_or_network(self):
        for installed in ("1.3.6", "9.9.9"):
            with self.subTest(installed=installed):
                result, output = self.run_step("version", REPORTED_VERSION=installed)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output, {"version": installed})
                self.assertEqual(self.network.read_text(), "")
                arguments = self.arguments.read_text().splitlines()
                self.assertEqual(len(arguments), 2)
                self.assertEqual(arguments[0], "-e")
                self.assertIn('packageVersion("xml2")', arguments[1])
                self.assertIn('Sys.getenv("XML2_LIB")', arguments[1])
                self.assertIn('Sys.getenv("XML2_USER_LIB")', arguments[1])

    def test_command_tripwires_are_active(self):
        for command in ("python", "python3", "curl", "wget"):
            with self.subTest(command=command):
                result, output = self.run_step("version", source=command)
                self.assertEqual(result.returncode, 97)
                self.assertEqual(output, {})
                self.assertEqual(self.network.read_text(), command + "\n")

    def test_old_step_fails_on_mocked_http429_but_new_step_never_invokes_lookup(self):
        fixture = self.root / "http429.py"
        fixture.write_text('''import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from unittest.mock import patch

def rate_limit(url, timeout):
    assert url == "https://cloud.r-project.org/src/contrib/PACKAGES"
    assert timeout == 20
    with Path(os.environ["FIXTURE_ROOT"], "network-attempts").open("a") as output:
        output.write("urllib.request.urlopen\\n")
    raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

with patch("urllib.request.urlopen", side_effect=rate_limit), \\
        patch("socket.socket", side_effect=AssertionError("live network forbidden")):
    exec(compile(sys.stdin.read(), "old-xml2-version", "exec"), {"__name__": "__main__"})
''')
        self.stub("python3", 'printf "%s\\n" python3 >> "$FIXTURE_ROOT/network-attempts"\n'
                  + f"exec {shlex.quote(sys.executable)} -I -B {shlex.quote(str(fixture))} \"$@\"\n")
        result, output = self.run_step("version", source=OLD_VERSION_SCRIPT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP Error 429: Too Many Requests", result.stderr)
        self.assertEqual(output, {})
        self.assertEqual(self.network.read_text().splitlines(), ["python3", "urllib.request.urlopen"])
        result, output = self.run_step("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, {"version": "1.3.6"})
        self.assertEqual(self.network.read_text(), "")

    def test_wrong_missing_or_unreadable_version_cannot_pass_exact_version_check(self):
        for installed, exit_code in (("9.9.9", "0"), ("", "0"), ("", "1")):
            with self.subTest(installed=installed, exit_code=exit_code):
                result, output = self.run_step("test2", REPORTED_VERSION=installed, RSCRIPT_EXIT=exit_code)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(output.get("status"), "passed")
                self.assertEqual(self.network.read_text(), "")

    def test_package_manager_contract_and_public_regression_outputs_are_unchanged(self):
        result, output = self.run_step("test6", {"steps.version.outputs.version": "1.3.6"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, {
            "current_version": "1.3.6", "latest_version": "not_applicable",
            "next_installed_version": "not_applicable", "decision": "not_applicable_package_manager",
            "regression_result": "Regression validation not applicable: tested package installed via package manager in Tests 1-5",
            "comparison": "The tested package is installed via a package manager in Tests 1-5, so version-to-version regression validation is not shown under the current policy.",
            "status": "skipped", "duration": "0",
        })
        self.assertEqual(self.network.read_text(), "")
        self.assertEqual(self.job["outputs"]["package_version"], "${{ steps.version.outputs.version || 'unknown' }}")
        self.assertEqual(self.job["outputs"]["regression_latest_version"], "${{ steps.test6.outputs.latest_version || 'unknown' }}")
        public = self.workflow["on"]["workflow_call"]["outputs"]
        self.assertEqual(public["regression_latest_version"]["value"], "${{ jobs.test-xml2.outputs.regression_latest_version }}")
        self.assertNotIn("latest", self.job["outputs"])
        self.assertNotIn("latest", public)
        self.assertNotIn("steps.version.outputs.latest", self.source)

    def test_summary_accepts_only_five_passed_core_statuses(self):
        result, output = self.run_step("summary", self.core_values())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, {"passed": "5", "failed": "0", "core_failed": "0", "duration": "10",
                                  "overall_status": "success", "badge_status": "passing"})

    def test_each_failed_skipped_empty_or_missing_core_result_keeps_summary_red(self):
        for i in range(1, 6):
            for status in ("failed", "skipped", "", None):
                with self.subTest(core=i, status=status):
                    values = self.core_values()
                    if status is None:
                        del values[f"steps.test{i}.outputs.status"]
                        del values[f"steps.test{i}.outputs.duration"]
                    else:
                        values[f"steps.test{i}.outputs.status"] = status
                    result, output = self.run_step("summary", values)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(output, {"passed": "4", "failed": "1", "core_failed": "1",
                                              "duration": "8" if status is None else "10",
                                              "overall_status": "failure", "badge_status": "failing"})

    def test_no_executed_core_tests_is_five_failures_not_a_pass(self):
        result, output = self.run_step("summary")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(output, {"passed": "0", "failed": "5", "core_failed": "5", "duration": "0",
                                  "overall_status": "failure", "badge_status": "failing"})


if __name__ == "__main__":
    unittest.main()
