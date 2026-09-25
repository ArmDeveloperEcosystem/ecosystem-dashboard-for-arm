"""Execute Kafka's real version-check shell with offline CLI fixtures, not Kafka."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-kafka.yml"
BASELINE = "4.1.2"
CANDIDATE = "4.2.0"
# Workflow before the scoped version checks, at e2c3d1025c3fa4b938cc950dd0fb127eb71c89a8.
ORIGINAL_SHA256 = "b08c4788b2fd336926e2296542abacc502efcaf995c1374a46429f6768ecd292"
OLD_BASELINE = '''# Kafka doesn't have a simple --version command on the main scripts usually,
# but we can check the jar or just use the version we downloaded.
# Or use kafka-topics.sh --version in newer versions

if kafka/bin/kafka-topics.sh --version &> /dev/null; then
   VERSION=$(kafka/bin/kafka-topics.sh --version | awk '{print $1}' || echo "unknown")
else
   # Fallback
   VERSION="${KAFKA_VERSION}"
fi

echo "version=$VERSION" >> $GITHUB_OUTPUT
echo "Detected Kafka version: $VERSION"
'''
OLD_CANDIDATE = '''NEXT_INSTALLED_VERSION=$("$NEXT_BIN" --version 2>/dev/null | awk '{print $1}' | head -n 1 || true)
if [ -z "$NEXT_INSTALLED_VERSION" ]; then
  NEXT_INSTALLED_VERSION="$LATEST"
fi
if [ "$NEXT_INSTALLED_VERSION" = "$LATEST" ]; then
'''
NEW_CANDIDATE = r'''NEXT_INSTALLED_VERSION=unknown
if NEXT_VERSION_OUTPUT=$("$NEXT_BIN" --version 2>/dev/null) && \
   NEXT_INSTALLED_VERSION=$(printf '%s\n' "$NEXT_VERSION_OUTPUT" | awk 'NR == 1 {print $1}') && \
   [ -n "$NEXT_INSTALLED_VERSION" ] && [ "$NEXT_INSTALLED_VERSION" = "$LATEST" ]; then
'''
VERSION_GUARD = '''             [ "${{ steps.version.outcome || 'skipped' }}" != "success" ] || \\
             [ "$CURRENT" != "$KAFKA_VERSION" ] || \\
'''
SUMMARY_GUARD = '''          if [ "${{ steps.install.outputs.install_status || 'failed' }}" != "success" ] || \\
             [ "${{ steps.version.outcome || 'skipped' }}" != "success" ] || \\
             [ "${{ steps.version.outputs.version || 'unknown' }}" != "$KAFKA_VERSION" ]; then
            CORE_FAILED=1
'''


class KafkaWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_bytes().decode("utf-8")
        self.workflow = yaml.load(self.source, Loader=yaml.BaseLoader)
        self.job = self.workflow["jobs"]["test-kafka"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        script = self.steps["test6"]["run"]
        start = script.index('  if [ -x "$NEXT_BIN" ]; then\n')
        self.candidate_check = script[start:script.index("\nelse\n", start)]
        self.baseline_gate = script[script.index("START_TIME=$(date +%s)"):
                                    script.index('LATEST="${KAFKA_NEXT_VERSION}"')]
        temporary = tempfile.TemporaryDirectory(prefix="kafka workflow ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash)
        for name in ("awk", "date"):
            executable = shutil.which(name)
            self.assertIsNotNone(executable)
            (self.bin / name).symlink_to(executable)
        self.output = self.root / "outputs"
        self.calls = self.root / "cli-calls"
        self.reached = self.root / "candidate-reached"
        self.baseline = self.root / "kafka/bin/kafka-topics.sh"
        self.candidate = self.root / "candidate/bin/kafka-topics.sh"
        for path in (self.baseline, self.candidate):
            path.parent.mkdir(parents=True)
            path.write_text(f"#!{self.bash}\n" + '''set -euo pipefail
[ "$#" -eq 1 ] && [ "$1" = --version ] || exit 97
printf '%s\\n' "$1" >> "$FIXTURE_ROOT/cli-calls"
printf '%s' "$CLI_OUTPUT"
printf '%s' "$CLI_STDERR" >&2
exit "$CLI_EXIT"
''')
            path.chmod(0o755)
        self.env = {**os.environ, **self.job["env"], "PATH": str(self.bin),
                    "HOME": str(self.root), "TMPDIR": str(self.root),
                    "GITHUB_OUTPUT": self.output.name, "FIXTURE_ROOT": str(self.root),
                    "NEXT_BIN": str(self.candidate), "CURRENT": BASELINE, "LATEST": CANDIDATE,
                    "CLI_OUTPUT": "", "CLI_STDERR": "", "CLI_EXIT": "0"}

    def run_shell(self, source, values=None, **environment):
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

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)
        for path in (self.output, self.calls, self.reached):
            path.write_text("")
        result = subprocess.run([self.bash, "-euo", "pipefail", "-c", script],
                                cwd=self.root, env={**self.env, **environment},
                                capture_output=True, text=True, timeout=10)
        pairs = [line.split("=", 1) for line in self.output.read_text().splitlines()]
        self.assertEqual(len(pairs), len(dict(pairs)), "duplicate output")
        return result, dict(pairs)

    def assert_failure(self, kind, result, output):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        if kind == "baseline":
            self.assertEqual(output, {"version": "unknown"})
        else:
            self.assertEqual(output["status"], "failed")
            self.assertEqual(output["decision"], "next_install_failed")
            self.assertNotIn("status=passed", self.output.read_text())
            self.assertNotIn("next_install_validated", self.output.read_text())
            self.assertNotIn("installed successfully", self.output.read_text())
            if output.get("next_installed_version") != "install_failed":
                self.assertEqual(output["regression_result"],
                                 "Next version CLI failed or did not report the expected version on Arm64")
                self.assertIn("CLI failed or did not report the expected version", output["comparison"])
                self.assertNotIn("reported a version mismatch", self.output.read_text())

    def test_only_authorized_version_checks_changed(self):
        current = textwrap.indent(self.steps["version"]["run"], "          ")
        self.assertEqual(self.source.count(current), 1)
        restored = self.source.replace(current, textwrap.indent(OLD_BASELINE, "          ", lambda _: True), 1)
        self.assertEqual(restored.count(VERSION_GUARD), 1)
        restored = restored.replace(VERSION_GUARD, "", 1)
        current_candidate = textwrap.indent(NEW_CANDIDATE, "              ")
        self.assertEqual(restored.count(current_candidate), 1)
        restored = restored.replace(current_candidate, textwrap.indent(OLD_CANDIDATE, "              "), 1)
        self.assertEqual(restored.count(SUMMARY_GUARD), 1)
        restored = restored.replace(SUMMARY_GUARD,
                                    '          if [ "${{ steps.install.outputs.install_status || \'failed\' }}" != "success" ]; then\n'
                                    '            CORE_FAILED=1\n', 1)
        new_message = "Next version CLI failed or did not report the expected version on Arm64"
        self.assertEqual(restored.count(new_message), 2)
        restored = restored.replace(new_message, "Next version installed but reported a version mismatch on Arm64")
        new_comparison = "the regression candidate ${LATEST} CLI failed or did not report the expected version on Arm64 (reported: ${NEXT_INSTALLED_VERSION:-unknown})."
        self.assertEqual(restored.count(new_comparison), 1)
        restored = restored.replace(new_comparison,
                                    "the regression candidate ${LATEST} extracted on Arm64 and reported version ${NEXT_INSTALLED_VERSION}, which does not match the requested upgrade target.", 1)
        self.assertEqual(hashlib.sha256(restored.encode("utf-8")).hexdigest(), ORIGINAL_SHA256)
        self.assertEqual(self.job["env"]["KAFKA_VERSION"], BASELINE)
        self.assertEqual(self.job["env"]["KAFKA_NEXT_VERSION"], CANDIDATE)
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        self.assertNotIn("continue-on-error", self.steps["version"])

    def test_baseline_zero_exit_correct_version_uses_one_cli_invocation(self):
        result, output = self.run_shell(self.steps["version"]["run"], CLI_OUTPUT=BASELINE + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, {"version": BASELINE})
        self.assertEqual(self.calls.read_text(), "--version\n")

    def test_baseline_zero_exit_wrong_empty_or_malformed_output_fails(self):
        for value in (CANDIDATE, "", " \t\n", "unavailable", "4.1.20"):
            with self.subTest(output=value):
                self.assert_failure("baseline", *self.run_shell(self.steps["version"]["run"], CLI_OUTPUT=value))
                self.assertEqual(self.calls.read_text(), "--version\n")

    def test_baseline_nonzero_exit_correct_empty_or_other_output_fails(self):
        for value in (BASELINE, "", "other"):
            with self.subTest(output=value):
                self.assert_failure("baseline", *self.run_shell(self.steps["version"]["run"], CLI_OUTPUT=value, CLI_EXIT="1"))
                self.assertEqual(self.calls.read_text(), "--version\n")

    def test_candidate_zero_exit_correct_version_uses_one_cli_invocation(self):
        result, output = self.run_shell(self.candidate_check, CLI_OUTPUT=CANDIDATE + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["next_installed_version"], CANDIDATE)
        self.assertEqual(output["status"], "passed")
        self.assertEqual(output["decision"], "next_install_validated")
        self.assertEqual(self.calls.read_text(), "--version\n")

    def test_candidate_zero_exit_wrong_empty_or_malformed_output_fails(self):
        for value in (BASELINE, "", " \t\n", "unavailable", "4.2.00"):
            with self.subTest(output=value):
                result, output = self.run_shell(self.candidate_check, CLI_OUTPUT=value)
                self.assert_failure("candidate", result, output)
                self.assertNotEqual(output["next_installed_version"], CANDIDATE)
                self.assertEqual(self.calls.read_text(), "--version\n")

    def test_candidate_nonzero_exit_correct_empty_or_other_output_fails(self):
        for value in (CANDIDATE, "", "other"):
            with self.subTest(output=value):
                result, output = self.run_shell(self.candidate_check, CLI_OUTPUT=value, CLI_EXIT="1")
                self.assert_failure("candidate", result, output)
                self.assertEqual(output["next_installed_version"], "unknown")
                self.assertEqual(self.calls.read_text(), "--version\n")

    def test_version_on_stderr_is_not_accepted_as_stdout(self):
        for kind, script, version in (("baseline", self.steps["version"]["run"], BASELINE),
                                      ("candidate", self.candidate_check, CANDIDATE)):
            with self.subTest(kind=kind):
                self.assert_failure(kind, *self.run_shell(script, CLI_STDERR=version))

    def test_missing_or_nonexecutable_cli_cannot_pass(self):
        for kind, script, path in (("baseline", self.steps["version"]["run"], self.baseline),
                                   ("candidate", self.candidate_check, self.candidate)):
            with self.subTest(kind=kind, state="not executable"):
                path.chmod(0o644)
                self.assert_failure(kind, *self.run_shell(script))
                self.assertEqual(self.calls.read_text(), "")
            with self.subTest(kind=kind, state="missing"):
                path.unlink()
                self.assert_failure(kind, *self.run_shell(script))
                self.assertEqual(self.calls.read_text(), "")

    def gate_values(self):
        return {"steps.install.outputs.install_status": "success",
                "steps.version.outcome": "success", "steps.version.outputs.version": BASELINE,
                **{f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)}}

    def run_gate(self, values):
        return self.run_shell(self.baseline_gate + 'printf reached > "$FIXTURE_ROOT/candidate-reached"\n', values)

    def assert_blocked(self, values):
        result, output = self.run_gate(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["decision"], "baseline_failed")
        self.assertEqual(output["status"], "skipped")
        self.assertEqual(output["next_installed_version"], "not_installed")
        self.assertEqual(self.reached.read_text(), "")
        self.assertEqual(self.calls.read_text(), "")

    def test_regression_gate_requires_successful_matching_baseline_version(self):
        for key, bad_values in (("steps.version.outcome", ("failure", "skipped", "cancelled", "", None)),
                                ("steps.version.outputs.version", (CANDIDATE, "unknown", "", None))):
            for bad in bad_values:
                with self.subTest(key=key, value=bad):
                    values = self.gate_values()
                    if bad is None:
                        del values[key]
                    else:
                        values[key] = bad
                    self.assert_blocked(values)

    def test_regression_gate_still_requires_install_and_all_five_core_checks(self):
        for key in ("steps.install.outputs.install_status", *(f"steps.test{i}.outputs.status" for i in range(1, 6))):
            for bad in ("failed", "", None):
                with self.subTest(key=key, value=bad):
                    values = self.gate_values()
                    if bad is None:
                        del values[key]
                    else:
                        values[key] = bad
                    self.assert_blocked(values)

    def test_matching_baseline_and_core_passes_allow_candidate_stage(self):
        result, output = self.run_gate(self.gate_values())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, {})
        self.assertEqual(self.reached.read_text(), "reached")

    def summary_values(self, regression_status="skipped"):
        return {**self.gate_values(),
                **{f"steps.test{i}.outputs.duration": "1" for i in range(1, 6)},
                "steps.test6.outputs.status": regression_status,
                "steps.test6.outputs.duration": "0"}

    def assert_version_failure_summary(self, values):
        result, output = self.run_shell(self.steps["summary"]["run"], values)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(output, {"passed": "5", "failed": "0", "skipped": "1",
                                  "duration": "5", "core_failed": "1",
                                  "overall_status": "failure", "badge_status": "failing"})

    def test_bad_or_missing_baseline_version_cannot_emit_successful_summary(self):
        for key, bad_values in (("steps.version.outcome", ("failure", "skipped", "cancelled", "", None)),
                                ("steps.version.outputs.version", (CANDIDATE, "unknown", "", None))):
            for bad in bad_values:
                with self.subTest(key=key, value=bad):
                    values = self.summary_values()
                    if bad is None:
                        del values[key]
                    else:
                        values[key] = bad
                    self.assert_version_failure_summary(values)

    def test_baseline_cli_failure_propagates_through_gate_and_summary(self):
        result, version = self.run_shell(self.steps["version"]["run"], CLI_OUTPUT=BASELINE, CLI_EXIT="1")
        self.assert_failure("baseline", result, version)
        values = self.summary_values()
        values["steps.version.outcome"] = "failure"
        values["steps.version.outputs.version"] = version["version"]
        self.assert_blocked(values)
        self.assert_version_failure_summary(values)

    def test_candidate_failure_keeps_core_badge_passing_but_overall_result_failed(self):
        result, candidate = self.run_shell(self.candidate_check, CLI_OUTPUT=CANDIDATE, CLI_EXIT="1")
        self.assert_failure("candidate", result, candidate)
        result, output = self.run_shell(self.steps["summary"]["run"], self.summary_values(candidate["status"]))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(output, {"passed": "5", "failed": "1", "skipped": "0",
                                  "duration": "5", "core_failed": "0",
                                  "overall_status": "failure", "badge_status": "passing"})

    def test_successful_versions_and_all_six_passes_keep_summary_green(self):
        result, output = self.run_shell(self.steps["summary"]["run"], self.summary_values("passed"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, {"passed": "6", "failed": "0", "skipped": "0",
                                  "duration": "5", "core_failed": "0",
                                  "overall_status": "success", "badge_status": "passing"})


if __name__ == "__main__":
    unittest.main()
