"""Execute Metricbeat workflow shells offline; fixtures do not run Metricbeat."""

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-metricbeat.yml"
sys.path.insert(0, str(ROOT / ".github/scripts"))
import package_observation_migration_audit as audit  # noqa: E402

BASELINE = "9.0.4"
CANDIDATE = "9.0.5"
UNCHANGED_SHA256 = "fcfc394f144c9ce3848da2dc5e9e835651dd118fdddc5ec372306e2aca5f1d5f"
HELP = "Usage:\n  metricbeat [flags]\n  metricbeat [command]\n\nAvailable Commands:\n  version  Show current version info\n"
MODULES = "Enabled:\nsystem\n\nDisabled:\napache\n"


def version_output(version):
    return f"metricbeat version {version} (arm64), libbeat {version} [fixture built unknown]\n"


class MetricbeatSmokeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)
        self.job = self.workflow["jobs"]["test-metricbeat"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        temporary = tempfile.TemporaryDirectory(prefix="metricbeat workflow ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash)
        for name in ("grep", "cp", "chmod", "tar", "mktemp"):
            executable = shutil.which(name)
            self.assertIsNotNone(executable)
            (self.bin / name).symlink_to(executable)
        self.output = self.root / "outputs"
        self.calls = self.root / "calls"
        self.base_home = self.root / "baseline package"
        self.base_home.mkdir()
        self.config = self.base_home / "metricbeat.yml"
        self.config.write_text("output.console.enabled: true\n")
        cli = '''if [ "$0" = "$FIXTURE_BASELINE" ]; then
  prefix=BASE
  home="$FIXTURE_BASE_HOME"
  config="$FIXTURE_CONFIG"
else
  prefix=NEXT
  home="${0%/*}"
  config="${home%/*}/metricbeat.yml"
fi
printf '%s %s\\n' "$prefix" "$*" >> "$FIXTURE_ROOT/calls"
case "$1" in
  version) [ "$#" -eq 1 ]; kind=VERSION;;
  --help) [ "$#" -eq 1 ]; kind=HELP;;
  modules|test)
    if [ "$1" = modules ]; then [ "$2" = list ]; kind=MODULES
    else [ "$2" = config ]; kind=CONFIG; fi
    shift 2
    [ "$#" -eq 6 ] && [ "$1" = --path.home ] && [ "$2" = "$home" ]
    [ "$3" = --path.config ] && [ "$4" = "$home" ]
    [ "$5" = -c ] && [ "$6" = "$config" ];;
  *) echo 'Unexpected Metricbeat command' >&2; exit 97;;
esac
value="${prefix}_${kind}_OUTPUT"
code="${prefix}_${kind}_EXIT"
signal="${prefix}_${kind}_SIGNAL"
printf '%s' "${!value}"
if [ -n "${!signal}" ]; then
  ulimit -c 0
  kill -s "${!signal}" "$$"
fi
exit "${!code}"
'''
        self.baseline = self.tool("metricbeat", cli)
        archive = self.root / "candidate.tar.gz"
        with tarfile.open(archive, "w:gz") as package:
            for name, data, mode in (
                ("metricbeat", self.script(cli).encode(), 0o755),
                ("metricbeat.yml", self.config.read_bytes(), 0o644),
            ):
                entry = tarfile.TarInfo(f"metricbeat-{CANDIDATE}-linux-arm64/{name}")
                entry.size = len(data)
                entry.mode = mode
                package.addfile(entry, io.BytesIO(data))
        self.tool("curl", '''printf 'curl %s\\n' "$*" >> "$FIXTURE_ROOT/calls"
[ "$#" -eq 4 ] && [ "$1" = -fsSL ] && [ "$3" = -o ] || exit 97
[ "$2" = "https://artifacts.elastic.co/downloads/beats/metricbeat/metricbeat-${NEXT_VERSION}-linux-arm64.tar.gz" ] || exit 97
if [ "$CURL_EXIT" != 0 ]; then exit "$CURL_EXIT"; fi
cp "$FIXTURE_ARCHIVE" "$4"
''')
        self.tool("timeout", '''[ "$#" -ge 4 ] && [ "$1" = --kill-after=5s ] || exit 97
case "$4" in
  version|--help) [ "$2" = 20s ] || exit 97;;
  modules|test) [ "$2" = 30s ] || exit 97;;
  *) exit 97;;
esac
printf 'timeout %s %s\\n' "$1" "$2" >> "$FIXTURE_ROOT/calls"
shift 2
exec "$@"
''')
        self.tool("date", '''[ "$#" -eq 1 ] && [ "$1" = +%s ] || exit 97
if [ -e "$FIXTURE_ROOT/date-started" ]; then printf '107\\n'
else : > "$FIXTURE_ROOT/date-started"; printf '100\\n'; fi
''')
        self.tool("realpath", 'printf "%s\\n" "$1"\n')
        self.tool("uname", 'printf "%s\\n" "$RUNNER_ARCH"\n')
        self.tool("file", '''if [ "$1" = -b ]; then
  [ "$#" -eq 2 ] || exit 97
  printf '%s\\n' "$FILE_OUTPUT"
else
  printf '%s: %s\\n' "$1" "$FILE_OUTPUT"
fi
exit "$FILE_EXIT"
''')
        self.tool("readelf", 'printf "%s\\n" "$READELF_OUTPUT"\nexit "$FILE_EXIT"\n')
        for name in ("wget", "python", "python3", "sudo", "install", "git"):
            self.tool(name, 'echo "Unexpected external command" >&2\nexit 98\n')
        self.env = {**os.environ, **self.job["env"], "PATH": str(self.bin),
                    "HOME": str(self.root), "TMPDIR": str(self.root),
                    "GITHUB_OUTPUT": str(self.output), "FIXTURE_ROOT": str(self.root),
                    "FIXTURE_BASELINE": str(self.baseline), "FIXTURE_BASE_HOME": str(self.base_home),
                    "FIXTURE_CONFIG": str(self.config), "FIXTURE_ARCHIVE": str(archive),
                    "CURL_EXIT": "0", "RUNNER_ARCH": "aarch64", "FILE_EXIT": "0",
                    "FILE_OUTPUT": "ELF 64-bit LSB executable, ARM aarch64", "READELF_OUTPUT": "Machine: AArch64"}
        for prefix, version in (("BASE", BASELINE), ("NEXT", CANDIDATE)):
            for kind, value in (("VERSION", version_output(version)), ("HELP", HELP),
                                ("MODULES", MODULES), ("CONFIG", "Config OK\n")):
                self.env[f"{prefix}_{kind}_OUTPUT"] = value
                self.env[f"{prefix}_{kind}_EXIT"] = "0"
                self.env[f"{prefix}_{kind}_SIGNAL"] = ""
        self.values = {"steps.install.outputs.baseline_version": BASELINE,
                       "steps.install.outputs.install_status": "success",
                       "steps.install.outputs.binary_path": str(self.baseline),
                       "steps.install.outputs.config_path": str(self.config),
                       "steps.install.outputs.extract_dir": str(self.base_home),
                       "steps.version.outcome": "success", "steps.version.outputs.version": BASELINE,
                       "steps.test6.outputs.decision": "next_install_validated"}
        for index in range(1, 7):
            self.values.update({f"steps.test{index}.outputs.status": "passed",
                                f"steps.test{index}.outcome": "success",
                                f"steps.test{index}.outputs.duration": "1"})

    def script(self, body):
        return f"#!{self.bash}\nset -euo pipefail\n" + body

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(self.script(body))
        path.chmod(0o755)
        return path

    def run_step(self, step, values=None, **environment):
        context = {**self.values, **(values or {})}

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if context.get(term):
                    return str(context[term])
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step]["run"])
        self.output.write_text("")
        self.calls.write_text("")
        (self.root / "date-started").unlink(missing_ok=True)
        result = subprocess.run([self.bash, "-euo", "pipefail", "-c", script], cwd=self.root,
                                env={**self.env, **environment}, capture_output=True, text=True, timeout=10)
        return result, dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def assert_failed(self, step, **environment):
        result, fields = self.run_step(step, **environment)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("status=passed", self.output.read_text())
        if step == "version":
            self.assertEqual(fields, {"version": "unknown"})
        else:
            self.assertEqual(fields["status"], "failed")
            self.assertEqual(fields["duration"], "7")
        return result, fields

    def test_only_scoped_assertions_and_summary_changed(self):
        unchanged = copy.deepcopy(self.workflow)
        for step in unchanged["jobs"]["test-metricbeat"]["steps"]:
            if step.get("id") in {"version", "test2", "test3", "test4", "test5", "test6", "summary"} or step["name"] == "Create test summary":
                step.pop("run", None)
        self.assertEqual(hashlib.sha256(json.dumps(unchanged, sort_keys=True).encode()).hexdigest(), UNCHANGED_SHA256)
        self.assertEqual(self.job["env"], {"BASELINE_VERSION": BASELINE, "NEXT_VERSION": CANDIDATE})
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        for step in ("test3", "test4", "test5", "test6"):
            self.assertNotIn("export config", self.steps[step]["run"])
            self.assertNotIn("strict.perms=false", self.steps[step]["run"])

    def test_status_duration_and_summary_outputs_remain_auditable(self):
        for step in (f"test{i}" for i in range(1, 7)):
            for field in ("status", "duration"):
                with self.subTest(step=step, field=field):
                    self.assertTrue(audit._step_emits_output(ROOT, self.steps[step], field))
        for field in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status"):
            self.assertTrue(audit._step_emits_output(ROOT, self.steps["summary"], field), field)

    def test_baseline_version_and_test2_require_actual_exact_cli(self):
        for step in ("version", "test2"):
            result, fields = self.run_step(step)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(version_output(BASELINE).strip(), result.stdout)
            self.assertEqual(self.calls.read_text().splitlines(), ["timeout --kill-after=5s 20s", "BASE version"])
            self.assertEqual(fields.get("version", fields.get("status")), BASELINE if step == "version" else "passed")

    def test_baseline_version_empty_wrong_noisy_or_nonzero_never_passes(self):
        for step in ("version", "test2"):
            for value in ("", "unknown", version_output(CANDIDATE), version_output(BASELINE + "0"),
                          "error " + version_output(BASELINE), version_output(BASELINE) + "error\n",
                          version_output(BASELINE).replace("arm64", "amd64")):
                with self.subTest(step=step, value=value):
                    self.assert_failed(step, BASE_VERSION_OUTPUT=value)
            for code in ("1", "124", "137"):
                for value in (version_output(BASELINE), "", "other"):
                    with self.subTest(step=step, code=code, value=value):
                        self.assert_failed(step, BASE_VERSION_EXIT=code, BASE_VERSION_OUTPUT=value)

    def test_test2_rejects_missing_or_wrong_expected_metadata(self):
        for field in ("steps.install.outputs.baseline_version", "steps.version.outputs.version"):
            for value in ("", CANDIDATE):
                result, outputs = self.run_step("test2", {field: value})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["status"], "failed")
                self.assertEqual(self.calls.read_text(), "")

    def test_baseline_help_config_and_modules_positive(self):
        for step, expected in (("test3", HELP), ("test4", "Config OK\n"), ("test5", MODULES)):
            with self.subTest(step=step):
                result, fields = self.run_step(step)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(fields, {"status": "passed", "duration": "7"})
                self.assertIn(expected, result.stdout)

    def test_baseline_help_rejects_empty_error_text_or_nonzero_matching_help(self):
        for value in ("", "metricbeat failed", "Usage: metricbeat failed", HELP.replace("Available Commands:", "Error:")):
            self.assert_failed("test3", BASE_HELP_OUTPUT=value)
        for code in ("1", "124", "137"):
            self.assert_failed("test3", BASE_HELP_EXIT=code)

    def test_baseline_modules_and_config_reject_matching_output_on_nonzero(self):
        for step, kinds in (("test4", ("CONFIG",)), ("test5", ("CONFIG", "MODULES"))):
            for kind in kinds:
                for code in ("1", "124", "137"):
                    with self.subTest(step=step, kind=kind, code=code):
                        self.assert_failed(step, **{f"BASE_{kind}_EXIT": code})
                for value in ("", "Error in modules manager", "Config OK but failed"):
                    self.assert_failed(step, **{f"BASE_{kind}_OUTPUT": value})

    def test_baseline_modules_require_real_sections_and_bundled_system_module(self):
        for value in ("Enabled:\nDisabled:\n", "system", "Enabled:\nsystem\n", "Disabled:\nsystem\n"):
            self.assert_failed("test5", BASE_MODULES_OUTPUT=value)

    def test_baseline_architecture_still_required(self):
        self.assert_failed("test5", RUNNER_ARCH="x86_64")
        self.assert_failed("test5", FILE_OUTPUT="ELF x86-64", READELF_OUTPUT="Machine: X86-64")
        self.assert_failed("test5", FILE_EXIT="1")

    def test_candidate_executes_all_actual_bounded_probes(self):
        result, fields = self.run_step("test6")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(fields["status"], "passed")
        self.assertEqual(fields["next_installed_version"], CANDIDATE)
        self.assertEqual(fields["decision"], "next_install_validated")
        self.assertEqual(fields["duration"], "7")
        for output in (version_output(CANDIDATE), HELP, "Config OK\n", MODULES):
            self.assertIn(output, result.stdout)
        calls = self.calls.read_text().splitlines()
        self.assertEqual([line for line in calls if line.startswith("timeout ")], [
            "timeout --kill-after=5s 20s", "timeout --kill-after=5s 20s",
            "timeout --kill-after=5s 30s", "timeout --kill-after=5s 30s"])
        self.assertEqual(sum(line == "NEXT version" for line in calls), 1)

    def test_candidate_bad_version_never_substitutes_requested_version(self):
        for value in ("", "unknown", version_output(BASELINE), version_output(CANDIDATE + "0"),
                      "error " + version_output(CANDIDATE), version_output(CANDIDATE) + "error\n",
                      version_output(CANDIDATE).replace("arm64", "amd64")):
            with self.subTest(value=value):
                _, fields = self.assert_failed("test6", NEXT_VERSION_OUTPUT=value)
                self.assertEqual(fields["next_installed_version"], "unknown")
        for code in ("1", "124", "137"):
            for value in (version_output(CANDIDATE), "", "other"):
                with self.subTest(code=code, value=value):
                    _, fields = self.assert_failed("test6", NEXT_VERSION_OUTPUT=value, NEXT_VERSION_EXIT=code)
                    self.assertEqual(fields["next_installed_version"], "unknown")

    def test_candidate_nonzero_help_config_modules_cannot_pass(self):
        for kind in ("HELP", "CONFIG", "MODULES"):
            for code in ("1", "124", "137"):
                with self.subTest(kind=kind, code=code):
                    _, fields = self.assert_failed("test6", **{f"NEXT_{kind}_EXIT": code})
                    self.assertEqual(fields["decision"], "next_install_failed")
                    self.assertEqual(fields["next_installed_version"], CANDIDATE)
            for value in ("", "metricbeat modules failed"):
                self.assert_failed("test6", **{f"NEXT_{kind}_OUTPUT": value})

    def test_cli_signals_with_matching_text_fail(self):
        self.assert_failed("version", BASE_VERSION_SIGNAL="TERM")
        self.assert_failed("test3", BASE_HELP_SIGNAL="TERM")
        self.assert_failed("test5", BASE_MODULES_SIGNAL="TERM")
        _, fields = self.assert_failed("test6", NEXT_VERSION_SIGNAL="TERM")
        self.assertEqual(fields["next_installed_version"], "unknown")

    def test_candidate_acquisition_and_architecture_fail_closed(self):
        _, fields = self.assert_failed("test6", CURL_EXIT="92")
        self.assertEqual(fields["next_installed_version"], "not_installed")
        self.assertNotIn("NEXT version", self.calls.read_text())
        self.assert_failed("test6", FILE_OUTPUT="ELF x86-64")
        self.assert_failed("test6", FILE_EXIT="1")

    def test_candidate_is_not_attempted_without_complete_baseline(self):
        cases = [{"steps.version.outputs.version": CANDIDATE}, {"steps.version.outcome": "failure"},
                 {"steps.install.outputs.install_status": "failed"}]
        cases += [{f"steps.test{i}.{field}": value} for i in range(1, 6)
                  for field, value in (("outputs.status", ""), ("outputs.status", "failed"), ("outcome", "failure"))]
        for values in cases:
            with self.subTest(values=values):
                result, fields = self.run_step("test6", values)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(fields["status"], "skipped")
                self.assertEqual(fields["decision"], "baseline_failed")
                self.assertEqual(fields["next_installed_version"], "not_installed")
                self.assertEqual(fields["duration"], "7")
                self.assertEqual(self.calls.read_text(), "")
                self.assertNotIn("passed smoke", self.output.read_text())

    def test_summary_six_real_passes(self):
        result, fields = self.run_step("summary")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields, {"passed": "6", "failed": "0", "skipped": "0", "duration": "6",
                                  "core_failed": "0", "overall_status": "success", "badge_status": "passing"})

    def test_summary_early_failure_counts_six_unexecuted_tests_as_skipped(self):
        values = {key: "" for key in self.values}
        values["steps.install.outputs.install_status"] = "failed"
        result, fields = self.run_step("summary", values)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(fields, {"passed": "0", "failed": "0", "skipped": "6", "duration": "0",
                                  "core_failed": "0", "overall_status": "failure", "badge_status": "failing"})

    def test_summary_rejects_raw_failure_even_with_passed_output(self):
        for index in range(1, 7):
            result, fields = self.run_step("summary", {f"steps.test{index}.outcome": "failure"})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((fields["passed"], fields["failed"], fields["skipped"]), ("5", "1", "0"))
            self.assertEqual(fields["core_failed"], "1" if index <= 5 else "0")
            self.assertEqual(fields["badge_status"], "failing" if index <= 5 else "passing")
            self.assertEqual(fields["overall_status"], "failure")

    def test_summary_rejects_missing_status_and_failed_version_prerequisite(self):
        cases = [{f"steps.test{i}.outputs.status": ""} for i in range(1, 7)]
        cases += [{"steps.version.outcome": "failure"}, {"steps.version.outputs.version": CANDIDATE},
                  {"steps.install.outputs.install_status": "failed"}]
        for values in cases:
            result, fields = self.run_step("summary", values)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(fields["overall_status"], "failure")
            self.assertEqual(sum(int(fields[key]) for key in ("passed", "failed", "skipped")), 6)

    def test_summary_counts_failed_core_and_unattempted_candidate_honestly(self):
        result, fields = self.run_step("summary", {"steps.test3.outputs.status": "failed", "steps.test3.outcome": "failure",
                                                   "steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": "baseline_failed"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((fields["passed"], fields["failed"], fields["skipped"], fields["core_failed"]), ("4", "1", "1", "1"))
        self.assertEqual(fields["badge_status"], "failing")

    def test_summary_text_does_not_claim_unexecuted_baseline_passed(self):
        step = next(step for step in self.job["steps"] if step["name"] == "Create test summary")
        self.assertNotIn("Pinned current version passed smoke tests", step["run"])
        self.assertIn("steps.summary.outputs.skipped", step["run"])


if __name__ == "__main__":
    unittest.main()
