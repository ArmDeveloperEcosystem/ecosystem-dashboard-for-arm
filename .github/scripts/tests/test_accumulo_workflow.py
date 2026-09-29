"""Exercise the actual Accumulo workflow shell and unchanged collector policy."""
import ast
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))
from package_result_policy import expected_regression_metadata, validate_six_test_result
import package_observation_migration_audit as audit

WORKFLOW = ROOT / ".github/workflows/test-accumulo.yml"


class AccumuloWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="accumulo-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-accumulo"]
        self.steps = {s["id"]: s for s in job["steps"] if "id" in s}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, **job["env"], RUNNER_TEMP=str(self.root),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.values = {"steps.install.outputs.install_status": "success",
                       "steps.install.outcome": "success",
                       "steps.version.outputs.version": "2.1.4"}
        for i in range(1, 7):
            self.values[f"steps.test{i}.outputs.status"] = "passed"
            self.values[f"steps.test{i}.outcome"] = "success"
        self.values["steps.test6.outputs.decision"] = "next_install_validated"
        result, _ = self.run_step("prepare")
        self.assertEqual(0, result.returncode, result.stderr)
        self.work = Path(self.env["ACCUMULO_WORK"])
        self.env.update(HADOOP_HOME=str(self.work / "hadoop"), ZOOKEEPER_HOME=str(self.work / "zk"))
        self.stub("timeout", 'shift 2\nexec "$@"\n')
        self.stub("uname", 'echo aarch64\n')
        self.stub("readelf", 'echo "Machine: ${NATIVE_MACHINE:-AArch64}"\n')
        self.stub("javac", 'exit "${COMPILE_EXIT:-0}"\n')
        self.fixture(self.work / "baseline", "2.1.4")
        self.fixture(self.work / "candidate", "3.0.0")

    def stub(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + script)
        path.chmod(0o755)

    def fixture(self, home, version):
        (home / "bin").mkdir(parents=True, exist_ok=True)
        (home / "lib/native").mkdir(parents=True, exist_ok=True)
        (home / "conf").mkdir(exist_ok=True)
        (home / "version").write_text(version)
        with zipfile.ZipFile(home / f"lib/accumulo-core-{version}.jar", "w") as jar:
            jar.writestr("META-INF/maven/org.apache.accumulo/accumulo-core/pom.properties",
                         f"version={version}\n")
        cli = home / "bin/accumulo"
        cli.write_text(r"""#!/bin/bash
set -euo pipefail
home=$(cd "$(dirname "$0")/.." && pwd)
test "$ACCUMULO_CONF_DIR" = "$home/conf"
case "$1" in
  version)
    if [ "${VERSION_MODE:-valid}" = valid ]; then
      cat "$home/version"; echo
    else
      printf '%s\n' "${VERSION_TEXT-}"
    fi
    exit "${VERSION_EXIT:-0}" ;;
  help) echo "${HELP_TEXT:-Usage: accumulo <command>}"; exit "${HELP_EXIT:-0}" ;;
  AccumuloProbe)
    echo "${PROBE_TEXT:-Accumulo key/mutation round trip passed}"
    exit "${PROBE_EXIT:-0}" ;;
  *) exit 1 ;;
esac
""")
        cli.chmod(0o755)
        helper = home / "bin/accumulo-util"
        helper.write_text('#!/bin/bash\ntest "$1" = build-native || exit 1\nexit "${NATIVE_EXIT:-0}"\n')
        helper.chmod(0o755)

    def render(self, script):
        def replace(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else self.values.get(
                    term, term if term.isdigit() else "")
                if value:
                    return str(value)
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, script)

    def run_script(self, script, **environment):
        output = self.root / "output"
        envfile = self.root / "environment"
        output.write_text("")
        envfile.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", self.render(script)],
                                cwd=self.root, env=dict(self.env, GITHUB_OUTPUT=str(output),
                                GITHUB_ENV=str(envfile), **environment),
                                text=True, capture_output=True, timeout=15)
        self.env.update(dict(line.split("=", 1) for line in envfile.read_text().splitlines()))
        fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, fields

    def run_step(self, name, **environment):
        return self.run_script(self.steps[name]["run"], **environment)

    def candidate_installer(self, exit_code=0):
        with (self.work / "functions.sh").open("a") as script:
            script.write(f'\ninstall_accumulo() {{ echo attempted > "$ACCUMULO_WORK/attempted"; return {exit_code}; }}\n')

    def assert_result(self, step, passed, **environment):
        result, fields = self.run_step(step, **environment)
        self.assertEqual(passed, result.returncode == 0, result.stdout + result.stderr)
        self.assertEqual("passed" if passed else "failed", fields["status"])
        self.assertIn("duration", fields)
        return fields

    def test_all_five_core_checks_and_candidate_positive(self):
        for i in range(1, 6):
            self.assert_result(f"test{i}", True)
        self.candidate_installer()
        fields = self.assert_result("test6", True, ACCUMULO_CONF_DIR="/wrong/baseline/conf")
        self.assertEqual("3.0.0", fields["next_installed_version"])
        self.assertEqual("next_install_validated", fields["decision"])

    def test_auditor_sees_terminal_status_and_duration_for_all_six_tests(self):
        for i in range(1, 7):
            for output in ("status", "duration"):
                with self.subTest(step=i, output=output):
                    self.assertTrue(audit._step_emits_output(ROOT, self.steps[f"test{i}"], output))

    def test_auditor_binds_only_approved_decision_status_pairs(self):
        self.assertEqual(
            (("baseline_failed", "skipped"), ("next_install_failed", "failed"),
             ("next_install_validated", "passed")),
            audit._step_literal_pairs(ROOT, self.steps["test6"]),
        )

    def test_finalizer_preserves_late_failure_exit_status_and_measured_duration(self):
        self.candidate_installer()
        self.stub("date", 'if [ -e "$RUNNER_TEMP/clock-started" ]; then echo 107; '
                  'else touch "$RUNNER_TEMP/clock-started"; echo 100; fi\n')
        for i in range(1, 7):
            with self.subTest(step=i):
                (self.root / "clock-started").unlink(missing_ok=True)
                script = self.steps[f"test{i}"]["run"].replace("finish 0", "exit 37\nfinish 0")
                result, fields = self.run_script(script)
                self.assertEqual(37, result.returncode, result.stdout + result.stderr)
                self.assertEqual("failed", fields["status"])
                self.assertEqual("7", fields["duration"])
                lines = (self.root / "output").read_text().splitlines()
                self.assertEqual(["status=failed"], [s for s in lines if s.startswith("status=")])
                self.assertEqual(["duration=7"], [s for s in lines if s.startswith("duration=")])
                if i == 6:
                    self.assertEqual("next_install_failed", fields["decision"])
                    self.assertNotIn("passed", fields["regression_result"])

    def test_baseline_guard_emits_one_terminal_skip_with_actual_duration(self):
        self.values["steps.test5.outputs.status"] = "failed"
        self.values["steps.test5.outcome"] = "failure"
        self.stub("date", 'if [ -e "$RUNNER_TEMP/clock-started" ]; then echo 107; '
                  'else touch "$RUNNER_TEMP/clock-started"; echo 100; fi\n')
        result, fields = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("skipped", fields["status"])
        self.assertEqual("baseline_failed", fields["decision"])
        self.assertEqual("7", fields["duration"])
        lines = (self.root / "output").read_text().splitlines()
        self.assertEqual(["status=skipped"], [s for s in lines if s.startswith("status=")])
        self.assertEqual(["duration=7"], [s for s in lines if s.startswith("duration=")])

    def test_failed_install_is_failure_for_every_core_check(self):
        self.values["steps.install.outputs.install_status"] = "failed"
        self.values["steps.install.outcome"] = "failure"
        for i in range(1, 6):
            self.assert_result(f"test{i}", False)
        result, fields = self.run_step("version")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("unknown", fields["version"])

    def test_dependency_install_failure_has_nonzero_exit_and_failed_output(self):
        bootstrap = self.root / ".github/actions/apt-bootstrap/bootstrap.sh"
        bootstrap.parent.mkdir(parents=True)
        bootstrap.write_text("exit 7\n")
        result, fields = self.run_step("install")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", fields["install_status"])

    def test_identity_requires_the_installed_jar_metadata(self):
        jar = self.work / "baseline/lib/accumulo-core-2.1.4.jar"
        with zipfile.ZipFile(jar, "w") as archive:
            archive.writestr("META-INF/maven/org.apache.accumulo/accumulo-core/pom.properties",
                             "version=2.1.5\n")
        self.assert_result("test1", False)

    def test_version_errors_digits_wrong_version_empty_and_nonzero_are_rejected(self):
        self.candidate_installer()
        for output, code in (("2.1.5", "0"), ("error 17: failed", "0"),
                             ("ZOOKEEPER_HOME=/missing is not valid", "0"),
                             ("", "0"), ("2.1.4", "7")):
            for step in ("test2", "test6"):
                with self.subTest(step=step, output=output, code=code):
                    fields = self.assert_result(step, False, VERSION_MODE="invalid",
                                                VERSION_TEXT=output, VERSION_EXIT=code)
                    if step == "test6":
                        self.assertEqual("not_installed", fields["next_installed_version"])
                        self.assertEqual("next_install_failed", fields["decision"])

    def test_candidate_correct_version_with_failing_exit_is_not_identity(self):
        self.candidate_installer()
        fields = self.assert_result("test6", False, VERSION_MODE="invalid",
                                    VERSION_TEXT="3.0.0", VERSION_EXIT="7")
        self.assertEqual("not_installed", fields["next_installed_version"])

    def test_candidate_runtime_failure_cannot_become_pass(self):
        self.candidate_installer()
        for environment in ({"HELP_EXIT": "7"}, {"NATIVE_EXIT": "7"},
                            {"COMPILE_EXIT": "7"}, {"PROBE_EXIT": "7"},
                            {"PROBE_TEXT": "ZOOKEEPER_HOME=/bad 3.0.0"}):
            with self.subTest(environment=environment):
                fields = self.assert_result("test6", False, **environment)
                self.assertEqual("next_install_failed", fields["decision"])
                self.assertEqual("3.0.0", fields["next_installed_version"])

    def test_core_help_native_and_runtime_failures_propagate(self):
        for step, environment in (
            ("test3", {"HELP_TEXT": "ZOOKEEPER_HOME=/missing"}),
            ("test3", {"HELP_EXIT": "7"}), ("test4", {"NATIVE_EXIT": "7"}),
            ("test4", {"NATIVE_MACHINE": "X86-64"}), ("test5", {"COMPILE_EXIT": "7"}),
            ("test5", {"PROBE_EXIT": "7"}), ("test5", {"PROBE_TEXT": "error 17"})):
            with self.subTest(step=step, environment=environment):
                self.assert_result(step, False, **environment)

    def test_candidate_install_failure_is_not_skipped(self):
        self.candidate_installer(exit_code=1)
        fields = self.assert_result("test6", False)
        self.assertEqual("next_install_failed", fields["decision"])

    def test_every_incomplete_or_raw_failed_baseline_guards_candidate(self):
        for i in range(1, 6):
            for status, outcome in (("failed", "failure"), ("skipped", "success"),
                                    ("", "success"), ("passed", "failure")):
                with self.subTest(i=i, status=status, outcome=outcome):
                    self.values[f"steps.test{i}.outputs.status"] = status
                    self.values[f"steps.test{i}.outcome"] = outcome
                    result, fields = self.run_step("test6")
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("skipped", fields["status"])
                    self.assertEqual("baseline_failed", fields["decision"])
                    self.assertEqual("not_installed", fields["next_installed_version"])
                    self.assertFalse((self.work / "attempted").exists())
                    self.values[f"steps.test{i}.outputs.status"] = "passed"
                    self.values[f"steps.test{i}.outcome"] = "success"

    def test_summary_counts_match_unchanged_collector_and_policy(self):
        # Load actual collector functions without executing network or publication code.
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        shell = next(s["run"] for s in action["runs"]["steps"] if s.get("id") == "collect")
        python = shell.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        tree = ast.parse(python)
        functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)],
                               type_ignores=[])
        namespace = dict(re=re, datetime=datetime, expected_regression_metadata=expected_regression_metadata)
        exec(compile(functions, "<unchanged-collector>", "exec"), namespace)
        for failed_cores, candidate in ((0, "passed"), (0, "failed"), (1, "skipped"), (5, "skipped")):
            with self.subTest(failed_cores=failed_cores, candidate=candidate):
                raw_steps = []
                for i in range(1, 7):
                    status = ("failed" if i <= failed_cores else "passed") if i <= 5 else candidate
                    outcome = "failure" if status == "failed" else "success"
                    self.values[f"steps.test{i}.outputs.status"] = status
                    self.values[f"steps.test{i}.outcome"] = outcome
                    raw_steps.append(dict(name=self.steps[f"test{i}"]["name"], conclusion=outcome))
                decision = {"passed": "next_install_validated", "failed": "next_install_failed",
                            "skipped": "baseline_failed"}[candidate]
                self.values["steps.test6.outputs.decision"] = decision
                result, fields = self.run_step("summary")
                details = namespace["extract_test_details"](
                    {"steps": raw_steps}, [{"status": candidate, "decision": decision}], candidate)
                required = validate_six_test_result(
                    details=details, passed=int(fields["passed"]), failed=int(fields["failed"]),
                    skipped=int(fields["skipped"]), core_failed=int(fields["core_failed"]),
                    decision=decision)
                self.assertEqual(required, fields["overall_status"])
                self.assertEqual("passing" if required == "success" else "failing", fields["badge_status"])
                self.assertEqual(required == "success", result.returncode == 0)
                self.assertEqual(6, sum(int(fields[k]) for k in ("passed", "failed", "skipped")))

    def test_candidate_failure_makes_badge_fail_despite_zero_core_failures(self):
        self.values["steps.test6.outputs.status"] = "failed"
        self.values["steps.test6.outcome"] = "failure"
        self.values["steps.test6.outputs.decision"] = "next_install_failed"
        result, fields = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("0", fields["core_failed"])
        self.assertEqual("5", fields["passed"])
        self.assertEqual("1", fields["failed"])
        self.assertEqual("failure", fields["overall_status"])
        self.assertEqual("failing", fields["badge_status"])

    def test_summary_rejects_missing_core_or_false_success_outcome(self):
        for status, outcome in (("", "success"), ("skipped", "success"), ("passed", "failure")):
            self.values["steps.test1.outputs.status"] = status
            self.values["steps.test1.outcome"] = outcome
            result, fields = self.run_step("summary")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("1", fields["core_failed"])
            self.assertEqual("0", fields["skipped"])

    def test_verified_transport_fallback_and_checksum_failure(self):
        payload = self.root / "artifact"
        payload.write_bytes(b"official fixture bytes")
        digest = hashlib.sha512(payload.read_bytes()).hexdigest()
        self.env["PAYLOAD"] = str(payload)
        self.stub("curl", r"""
printf '%s\n' "$*" >> "$RUNNER_TEMP/curl.calls"
target=""
while [ "$#" -gt 0 ]; do
  case "$1" in --output) target="$2"; shift ;; esac
  url="$1"; shift
done
case "$url" in *archive.apache.org*) exit 28 ;; esac
if [ "${ALL_DOWNLOADS_FAIL:-0}" = 1 ]; then exit 28; fi
cp "$PAYLOAD" "$target"
""")
        # Portable checksum implementation for macOS; hashes actual fixture bytes.
        checksum = self.bin / "sha512sum"
        checksum.write_text(f"#!{sys.executable}\nimport hashlib,sys\n"
                            "digest,path=sys.stdin.read().strip().split(None,1)\n"
                            "sys.exit(0 if hashlib.sha512(open(path,'rb').read()).hexdigest()==digest else 1)\n")
        checksum.chmod(0o755)
        for requested, all_fail, passed in ((digest, "0", True), ("0" * 128, "0", False),
                                           (digest, "1", False)):
            destination = self.root / f"download-{all_fail}-{requested[:8]}"
            result, _ = self.run_script(
                f'set -euo pipefail\nsource "$ACCUMULO_WORK/functions.sh"\n'
                f'download_verified "{destination}" "{requested}" '
                'https://archive.apache.org/fixture https://repo.maven.apache.org/fixture\n',
                ALL_DOWNLOADS_FAIL=all_fail)
            self.assertEqual(passed, result.returncode == 0, result.stderr)
            self.assertEqual(passed, destination.exists())
            self.assertFalse(Path(str(destination) + ".part").exists())
        calls = (self.root / "curl.calls").read_text()
        self.assertIn("--proto =https --proto-redir =https", calls)
        self.assertIn("--connect-timeout 10 --max-time 120", calls)


if __name__ == "__main__":
    unittest.main()
