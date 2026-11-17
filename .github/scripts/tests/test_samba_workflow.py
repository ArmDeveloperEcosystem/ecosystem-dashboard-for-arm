"""Exercise Samba's Test 6 and summary result contract with offline fixtures."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-samba.yml"
BASELINE = "4.23.6"
CANDIDATE = "4.23.7"
REGRESSION_OUTPUTS = {
    "current_version",
    "latest_version",
    "next_installed_version",
    "decision",
    "regression_result",
    "comparison",
    "status",
    "duration",
}
SUMMARY_OUTPUTS = {
    "passed",
    "failed",
    "skipped",
    "core_failed",
    "duration",
    "overall_status",
    "badge_status",
}


class SambaWorkflowContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="samba-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-samba"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.output = self.root / "outputs"
        self.trace = self.root / "trace"
        self.env = {
            **os.environ,
            **self.job["env"],
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "GITHUB_OUTPUT": str(self.output),
            "RUNNER_TEMP": str(self.root),
            "TMPDIR": str(self.root),
            "TRACE": str(self.trace),
            "CANDIDATE_VERSION": CANDIDATE,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.values = {}
        for number in range(1, 7):
            self.values[f"steps.test{number}.outputs.status"] = "passed"
            self.values[f"steps.test{number}.outputs.duration"] = str(number)
            self.values[f"steps.test{number}.outcome"] = "success"
        self.values.update(
            {
                "steps.version.outputs.version": BASELINE,
                "steps.version.outputs.latest": CANDIDATE,
                "steps.version.outputs.lookup_status": "success",
                "steps.test6.outputs.decision": "next_install_validated",
            }
        )
        self.stub(
            "curl",
            r'''
import os
from pathlib import Path
import sys

with open(os.environ["TRACE"], "a") as trace:
    trace.write("curl\n")
if os.environ.get("FAIL_STAGE") == "download":
    raise SystemExit(22)
args = sys.argv[1:]
target = Path(args[args.index("-o") + 1])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(b"offline Samba archive fixture")
''',
        )
        self.stub(
            "tar",
            r'''
import os
from pathlib import Path
import sys

with open(os.environ["TRACE"], "a") as trace:
    trace.write("tar\n")
args = sys.argv[1:]
destination = Path(args[args.index("-C") + 1])
source = next(Path(arg) for arg in args if arg.endswith(".tar.gz"))
version = source.name.removeprefix("samba-").removesuffix(".tar.gz")
tree = destination / f"samba-{version}"
tree.mkdir(parents=True, exist_ok=True)
configure = tree / "configure"
configure.write_text("#!/bin/bash\nexit 0\n")
configure.chmod(0o755)
''',
        )
        self.stub(
            "make",
            r'''
import os
from pathlib import Path
import sys

with open(os.environ["TRACE"], "a") as trace:
    trace.write("make " + " ".join(sys.argv[1:]) + "\n")
if os.environ.get("FAIL_STAGE") == "build":
    raise SystemExit(9)
binary = Path.cwd() / "bin/smbclient"
binary.parent.mkdir(parents=True, exist_ok=True)
binary.write_text(
    "#!/bin/bash\n"
    "if [ \"${1:-}\" = --version ]; then echo 'Version "
    + os.environ["CANDIDATE_VERSION"]
    + "'; else echo 'Connection to localhost failed: fixture'; fi\n"
)
binary.chmod(0o755)
''',
        )
        self.stub(
            "timeout",
            r'''
import os
import sys

args = sys.argv[1:]
while args and args[0].startswith("--"):
    args.pop(0)
if args and (args[0].endswith("s") or args[0].isdigit()):
    args.pop(0)
os.execvp(args[0], args)
''',
        )

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    @staticmethod
    def render(source, values):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    value = term[1:-1]
                else:
                    value = values.get(term, "")
                if value:
                    return str(value)
            return ""

        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)

    def run_step(self, name, values=None, **environment):
        bindings = {**self.values, **(values or {})}
        step = self.steps[name]
        step_env = {
            key: self.render(str(value), bindings)
            for key, value in step.get("env", {}).items()
        }
        script = self.render(step["run"], bindings)
        script = script.replace("/tmp/samba-", str(self.root / "samba-"))
        self.output.write_text("")
        self.trace.write_text("")
        result = subprocess.run(
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.root,
            env={**self.env, **step_env, **environment},
            capture_output=True,
            text=True,
            timeout=15,
        )
        fields = dict(
            line.split("=", 1)
            for line in self.output.read_text().splitlines()
            if "=" in line
        )
        return result, fields

    def assert_complete_regression(self, fields):
        self.assertTrue(
            REGRESSION_OUTPUTS.issubset(fields),
            f"missing outputs: {sorted(REGRESSION_OUTPUTS - fields.keys())}; got {fields}",
        )
        self.assertEqual(BASELINE, fields["current_version"])
        self.assertRegex(fields["duration"], r"^[0-9]+$")
        self.assertTrue(fields["regression_result"])
        self.assertTrue(fields["comparison"])

    def test_next_index_lookup_failure_emits_complete_failed_result(self):
        result, fields = self.run_step(
            "test6",
            {
                "steps.version.outputs.latest": "unknown",
                "steps.version.outputs.lookup_status": "lookup_failed",
            },
        )
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_complete_regression(fields)
        self.assertEqual("unknown", fields["latest_version"])
        self.assertEqual("not_installed", fields["next_installed_version"])
        self.assertEqual("failed", fields["status"])
        self.assertEqual("next_lookup_failed", fields["decision"])
        self.assertEqual("", self.trace.read_text())

    def test_candidate_download_and_build_failures_emit_complete_failed_results(self):
        for stage in ("download", "build"):
            with self.subTest(stage=stage):
                result, fields = self.run_step("test6", FAIL_STAGE=stage)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assert_complete_regression(fields)
                self.assertEqual(CANDIDATE, fields["latest_version"])
                self.assertEqual("not_installed", fields["next_installed_version"])
                self.assertEqual("failed", fields["status"])
                self.assertEqual("next_install_failed", fields["decision"])
                trace = self.trace.read_text()
                self.assertIn("curl\n", trace)
                self.assertEqual(stage == "build", "make " in trace)

    def test_no_newer_stable_emits_truthful_skip_without_candidate_execution(self):
        result, fields = self.run_step(
            "test6",
            {
                "steps.version.outputs.latest": "",
                "steps.version.outputs.lookup_status": "no_newer_stable",
            },
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_complete_regression(fields)
        self.assertEqual("unknown", fields["latest_version"])
        self.assertEqual("skipped", fields["status"])
        self.assertEqual("no_newer_stable_available", fields["decision"])
        self.assertEqual("", self.trace.read_text())

    def test_summary_fails_run_and_badge_when_test6_fails(self):
        result, fields = self.run_step(
            "summary",
            {
                "steps.test6.outputs.status": "failed",
                "steps.test6.outputs.decision": "next_lookup_failed",
                "steps.test6.outcome": "failure",
            },
        )
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(SUMMARY_OUTPUTS, set(fields))
        self.assertEqual(
            ("5", "1", "0", "0"),
            tuple(fields[key] for key in ("passed", "failed", "skipped", "core_failed")),
        )
        self.assertEqual("failure", fields["overall_status"])
        self.assertEqual("failing", fields["badge_status"])
        self.assertEqual("${{ steps.summary.outputs.overall_status || 'failure' }}",
                         self.job["outputs"]["run_status"])
        self.assertEqual("${{ steps.summary.outputs.badge_status || 'failing' }}",
                         self.job["outputs"]["badge_status"])

    def test_summary_counts_approved_no_newer_skip(self):
        result, fields = self.run_step(
            "summary",
            {
                "steps.test6.outputs.status": "skipped",
                "steps.test6.outputs.decision": "no_newer_stable_available",
                "steps.test6.outcome": "success",
            },
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(SUMMARY_OUTPUTS, set(fields))
        self.assertEqual(
            ("5", "0", "1", "0"),
            tuple(fields[key] for key in ("passed", "failed", "skipped", "core_failed")),
        )
        self.assertEqual("success", fields["overall_status"])
        self.assertEqual("passing", fields["badge_status"])


if __name__ == "__main__":
    unittest.main()
