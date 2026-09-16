"""Run the actual Multipass workflow shell with isolated command fixtures, not a VM."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as observation_audit
import package_result_policy as result_policy


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-multipass.yml"
VERSION = "1.16.4"
CERT = "/var/snap/multipass/common/data/multipassd/multipass_root_cert.pem"
CERT_ERROR = f"[error] [client] Caught an unhandled exception: failed to open file '{CERT}': No such file or directory(2)\n"
HELP = """Usage: multipass [options] <command>
Create, control and connect to Ubuntu instances.
Available commands:
  find          Display available images to create instances from
  help          Display help about a command
"""
# v1.16.4 JsonFormatter::format(FindReply) returns an object, not an array.
# https://github.com/canonical/multipass/blob/v1.16.4/src/client/cli/formatter/json_formatter.cpp#L28-L52
# https://github.com/canonical/multipass/blob/v1.16.4/src/client/cli/formatter/json_formatter.cpp#L333-L341
IMAGE = {"os": "Ubuntu", "release": "24.04 LTS", "version": "20260915",
         "remote": "", "aliases": ["noble", "lts"]}
FIND = json.dumps({"errors": [], "images": {"24.04": IMAGE}, "blueprints (deprecated)": {}}) + "\n"


class MultipassWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="multipass-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("bash", "date", "cat", "grep"):
            (self.bin / name).symlink_to(shutil.which(name))
        (self.bin / "python3").symlink_to(sys.executable)
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.job = self.workflow["jobs"]["test-multipass"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = dict(PATH=str(self.bin), HOME=str(self.root), TMPDIR=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"), PYTHONDONTWRITEBYTECODE="1",
                        CALLS=str(self.root / "calls"), CERT_CALLS=str(self.root / "cert-calls"),
                        ACTIVE_CALLS=str(self.root / "active-calls"),
                        ARCH="aarch64", SNAP_RC="0", START_RC="0", ACTIVE_RC="0", CERT_RC="0",
                        ACTIVE_READY_AFTER="1", CERT_READY_AFTER="1", TIMEOUT_TARGET="",
                        VERSION_STDOUT=json.dumps({"multipass": VERSION, "multipassd": VERSION}) + "\n",
                        VERSION_STDERR="", VERSION_RC="0",
                        BANNER_STDOUT=f"multipass   {VERSION}\nmultipassd  {VERSION}\n",
                        BANNER_STDERR="", BANNER_RC="0", HELP_STDOUT=HELP, HELP_STDERR="", HELP_RC="0",
                        FIND_STDOUT=FIND, FIND_STDERR="", FIND_RC="0")
        self.values = {
            "runner.environment": "github-hosted",
            "steps.install.outcome": "success",
            "steps.install.outputs.install_status": "success",
            "steps.version.outcome": "success",
            "steps.version.outputs.version": VERSION,
            "steps.test6.outcome": "success",
            "steps.test6.outputs.status": "skipped",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outputs.duration": "0",
        }
        for i in range(1, 6):
            self.values.update({f"steps.test{i}.outcome": "success",
                                f"steps.test{i}.outputs.status": "passed",
                                f"steps.test{i}.outputs.duration": str(i)})
        self.tool("multipass", """
printf 'multipass %s\n' "$*" >> "$CALLS"
case "$*" in
  'version --format json')
    printf '%s' "$VERSION_STDOUT"
    printf '%s' "$VERSION_STDERR" >&2
    exit "$VERSION_RC" ;;
  --version)
    printf '%s' "$BANNER_STDOUT"
    printf '%s' "$BANNER_STDERR" >&2
    exit "$BANNER_RC" ;;
  --help)
    test "$LC_ALL" = C
    printf '%s' "$HELP_STDOUT"
    printf '%s' "$HELP_STDERR" >&2
    exit "$HELP_RC" ;;
  'find --format json')
    printf '%s' "$FIND_STDOUT"
    printf '%s' "$FIND_STDERR" >&2
    exit "$FIND_RC" ;;
  *) exit 99 ;;
esac
""")
        # PATH contains no real sudo, snap, systemctl, or network tools.
        self.tool("sudo", f"""
printf 'sudo %s\n' "$*" >> "$CALLS"
case "$*" in
  'snap install multipass') exit "$SNAP_RC" ;;
  'systemctl start snap.multipass.multipassd.service') exit "$START_RC" ;;
  'systemctl is-active --quiet snap.multipass.multipassd.service')
    COUNT=0
    if [ -f "$ACTIVE_CALLS" ]; then read -r COUNT < "$ACTIVE_CALLS"; fi
    COUNT=$((COUNT + 1))
    echo "$COUNT" > "$ACTIVE_CALLS"
    [ "$COUNT" -ge "$ACTIVE_READY_AFTER" ] || exit 3
    exit "$ACTIVE_RC" ;;
  'test -s {CERT}')
    COUNT=0
    if [ -f "$CERT_CALLS" ]; then read -r COUNT < "$CERT_CALLS"; fi
    COUNT=$((COUNT + 1))
    echo "$COUNT" > "$CERT_CALLS"
    [ "$COUNT" -ge "$CERT_READY_AFTER" ] || exit 1
    exit "$CERT_RC" ;;
  *) exit 99 ;;
esac
""")
        # Validate the real timeout invocation; inject expiration without waiting minutes.
        self.tool("timeout", """
printf 'timeout %s %s %s\n' "$1" "$2" "$3" >> "$CALLS"
case "$1:$2:$3" in
  --kill-after=5s:300s:sudo|--kill-after=5s:30s:sudo|--kill-after=2s:5s:sudo|\
  --kill-after=5s:120s:bash|--kill-after=5s:30s:multipass|--kill-after=5s:120s:multipass) ;;
  *) exit 98 ;;
esac
shift 2
if [ "$1" = "$TIMEOUT_TARGET" ]; then exit 124; fi
exec "$@"
""")
        self.tool("sleep", 'test "$*" = 2\necho sleep >> "$CALLS"\n')
        self.tool("uname", 'test "$*" = -m\nprintf "%s\\n" "$ARCH"\n')

    def tool(self, name, script):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + script)
        path.chmod(0o755)

    def render(self, text):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if self.values.get(term):
                    return str(self.values[term])
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, text)

    def run_step(self, name, **overrides):
        step = self.steps[name]
        output = self.root / "output"
        output.write_text("")
        (self.root / "calls").write_text("")
        for counter in ("cert-calls", "active-calls"):
            (self.root / counter).unlink(missing_ok=True)
        env = {**self.env,
               **{key: self.render(str(value)) for key, value in step.get("env", {}).items()},
               **overrides}
        result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", self.render(step["run"])],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
        pairs = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(pair) == 2 for pair in pairs), pairs)
        fields = dict(pairs)
        self.assertEqual(len(pairs), len(fields), "Duplicate output keys")
        return result, fields

    def rejected(self, step, **overrides):
        result, fields = self.run_step(step, **overrides)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", fields.get("status"))
        self.assertRegex(fields.get("duration", ""), r"^[0-9]+$")
        return result, fields

    def record(self, step, result, fields):
        self.values[f"steps.{step}.outcome"] = "success" if result.returncode == 0 else "failure"
        self.values.update({f"steps.{step}.outputs.{key}": value for key, value in fields.items()})

    def calls(self):
        return (self.root / "calls").read_text()

    def test_scope_and_shell_syntax(self):
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual({"contents": "read"}, self.workflow["permissions"])
        self.assertEqual({f"test{i}" for i in range(1, 7)},
                         {name for name in self.steps if re.fullmatch(r"test\d+", name)})
        self.assertEqual(8, self.steps["install"]["timeout-minutes"])
        # runner is available in step env; environment distinguishes hosted from shared runners.
        # https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#runner-context
        self.assertEqual("${{ runner.environment }}", self.steps["install"]["env"]["RUNNER_ENVIRONMENT"])
        for step in self.job["steps"]:
            if "run" in step:
                checked = subprocess.run(["/bin/bash", "-n"], input=self.render(step["run"]),
                                         text=True, capture_output=True)
                self.assertEqual(0, checked.returncode, checked.stderr)
        self.assertNotRegex(WORKFLOW.read_text(), r"multipass (?:launch|start|exec)|/dev/kvm|upload-artifact|self-hosted")

    def test_hosted_install_waits_for_both_daemon_and_certificate(self):
        result, fields = self.run_step("install", ACTIVE_READY_AFTER="3", CERT_READY_AFTER="4")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual({"install_status": "success"}, fields)
        self.assertEqual("6", (self.root / "active-calls").read_text().strip())
        self.assertEqual("4", (self.root / "cert-calls").read_text().strip())
        self.assertEqual(5, self.calls().splitlines().count("sleep"))
        self.assertEqual(1, self.calls().splitlines().count("sudo systemctl start snap.multipass.multipassd.service"))

    def test_shared_or_unknown_runner_and_wrong_arch_cannot_mutate_services(self):
        for environment, arch in (("self-hosted", "aarch64"), ("", "aarch64"),
                                  ("github-hosted", "x86_64")):
            with self.subTest(environment=environment, arch=arch):
                result, fields = self.run_step("install", RUNNER_ENVIRONMENT=environment, ARCH=arch)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", fields["install_status"])
                self.assertEqual("", self.calls())

    def test_install_or_start_failure_is_not_ready(self):
        for env in ({"SNAP_RC": "1"}, {"START_RC": "5"}, {"TIMEOUT_TARGET": "sudo"},
                    {"TIMEOUT_TARGET": "bash"}):
            with self.subTest(env=env):
                result, fields = self.run_step("install", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", fields["install_status"])
                self.assertNotIn("root certificate ready", result.stdout)

    def test_missing_certificate_or_inactive_daemon_exhausts_bounded_wait(self):
        for env, counter in (({"CERT_RC": "1"}, "cert-calls"), ({"ACTIVE_RC": "3"}, "active-calls")):
            with self.subTest(env=env):
                result, fields = self.run_step("install", **env)
                self.assertEqual(1, result.returncode)
                self.assertEqual("failed", fields["install_status"])
                self.assertEqual("30", (self.root / counter).read_text().strip())
                self.assertIn("readiness failed", result.stderr)

    def test_successful_cli_checks_keep_output_and_six_test_policy(self):
        for step in ("install", "version", "test1", "test2", "test3", "test4", "test5", "test6"):
            result, fields = self.run_step(step)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.record(step, result, fields)
            if re.fullmatch(r"test[1-5]", step):
                self.assertEqual("passed", fields["status"])
                self.assertRegex(fields["duration"], r"^[0-9]+$")
        self.assertEqual(VERSION, self.values["steps.version.outputs.version"])
        self.assertEqual("not_applicable_package_manager", fields["decision"])
        self.assertEqual("skipped", fields["status"])
        for key in ("latest_version", "next_installed_version"):
            self.assertEqual("not_applicable", fields[key])
        result, summary = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1", "0", "success", "passing"),
                         tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status", "badge_status")))
        details = [{"name": self.steps[f"test{i}"]["name"], "status": "passed"} for i in range(1, 6)]
        details.append({"name": self.steps["test6"]["name"], **fields})
        self.assertEqual("success", result_policy.validate_six_test_result(
            details=details, passed=5, failed=0, skipped=1, core_failed=0, decision=fields["decision"]))

    def test_version_errors_do_not_publish_a_fallback(self):
        for env in ({"VERSION_RC": "7"}, {"VERSION_STDOUT": CERT_ERROR},
                    {"VERSION_STDOUT": "{}"}, {"VERSION_STDOUT": "[]"},
                    {"VERSION_STDOUT": '{"multipass": "unknown"}'},
                    {"VERSION_STDOUT": '{"multipass": 1164}'}, {"TIMEOUT_TARGET": "multipass"}):
            with self.subTest(env=env):
                result, fields = self.run_step("version", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("version", fields)
                self.assertNotIn("sudo", self.calls())

    def test_failed_cli_producers_retain_exact_exit_and_both_streams(self):
        for step, prefix in (("version", "VERSION"), ("test2", "BANNER"),
                             ("test3", "HELP"), ("test4", "FIND")):
            for rc in (1, 7, 124, 137, 139):
                with self.subTest(step=step, rc=rc):
                    env = {f"{prefix}_RC": str(rc), f"{prefix}_STDERR": CERT_ERROR}
                    result, fields = self.run_step(step, **env)
                    self.assertEqual(rc, result.returncode)
                    self.assertIn(self.env[f"{prefix}_STDOUT"], result.stdout)
                    self.assertIn(CERT_ERROR, result.stderr)
                    self.assertIn(f"exit={rc}", result.stdout)
                    if step != "version":
                        self.assertEqual("failed", fields["status"])
                        self.assertRegex(fields["duration"], r"^[0-9]+$")

    def test_cli_timeout_cannot_pass(self):
        for step in ("test2", "test3", "test4"):
            with self.subTest(step=step):
                result, _ = self.rejected(step, TIMEOUT_TARGET="multipass")
                self.assertEqual(124, result.returncode)
                self.assertIn("exit=124", result.stdout)

    def test_invalid_or_mismatched_version_banner_fails(self):
        for banner in ("", "multipass version failed\n", "multipass 9.9.9\n",
                       "multipassd 1.16.4\n", CERT_ERROR, self.env["BANNER_STDOUT"] * 2):
            with self.subTest(banner=banner):
                self.rejected("test2", BANNER_STDOUT=banner)

    def test_help_requires_real_stdout_usage_and_commands(self):
        for help_text in ("", CERT_ERROR, "Image release usage launch version help\n",
                          HELP.replace("Usage: multipass", "Usage: unrelated"),
                          HELP.replace("  find ", "  other "), HELP.replace("  help ", "  other ")):
            with self.subTest(help_text=help_text):
                self.rejected("test3", HELP_STDOUT=help_text)
        self.rejected("test3", HELP_STDOUT="", HELP_STDERR=HELP)

    def test_active_daemon_and_installed_package_cannot_rescue_failed_cli(self):
        result, _ = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        for step, prefix in (("test3", "HELP"), ("test4", "FIND")):
            result, _ = self.rejected(step, **{f"{prefix}_RC": "1", f"{prefix}_STDOUT": "",
                                              f"{prefix}_STDERR": CERT_ERROR})
            self.assertIn(CERT_ERROR, result.stderr)
            self.assertNotIn("sudo", self.calls())
            self.assertNotIn("snap", self.calls())

    def test_active_daemon_valid_payload_with_failed_exit_cannot_turn_summary_green(self):
        original = dict(self.values)
        for step, prefix in (("test3", "HELP"), ("test4", "FIND")):
            for rc in (7, 124):
                with self.subTest(step=step, rc=rc):
                    self.values = dict(original)
                    result, fields = self.run_step("install")
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn("root certificate ready", result.stdout)
                    self.record("install", result, fields)
                    result, fields = self.rejected(step, **{f"{prefix}_RC": str(rc)})
                    self.assertEqual(rc, result.returncode)
                    self.assertIn(self.env[f"{prefix}_STDOUT"], result.stdout)
                    self.record(step, result, fields)
                    # A stale passed label must not override the producer's failed raw outcome.
                    self.values[f"steps.{step}.outputs.status"] = "passed"
                    result, regression = self.run_step("test6")
                    self.assertEqual("baseline_failed", regression["decision"])
                    self.record("test6", result, regression)
                    result, summary = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("4", "1", "1", "1", "failure", "failing"),
                                     tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status", "badge_status")))

    def test_find_positive_records_allow_empty_aliases_and_remote(self):
        images = {"24.04": IMAGE, "core:core24": {**IMAGE, "aliases": [], "remote": "core"}}
        result, fields = self.run_step("test4", FIND_STDOUT=json.dumps({"errors": [], "images": images}))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", fields["status"])
        self.assertIn("Validated 2 available image records", result.stdout)

    def test_find_rejects_empty_malformed_wrong_shape_and_errors(self):
        payloads = ["", "Image release query failed\n", CERT_ERROR, FIND[:-3], "null", "[]", "{}",
                    '{"errors": [], "images": {}}', '{"errors": [], "images": []}',
                    '{"errors": [], "images": "Image release"}',
                    json.dumps({"images": {"24.04": IMAGE}}),
                    json.dumps({"errors": ["failed"], "images": {"24.04": IMAGE}}),
                    json.dumps({"errors": "", "images": {"24.04": IMAGE}}),
                    json.dumps({"errors": [], "blueprints (deprecated)": {"24.04": IMAGE}})]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.rejected("test4", FIND_STDOUT=payload)
        self.rejected("test4", FIND_STDOUT="", FIND_STDERR=FIND)

    def test_find_rejects_incomplete_or_mistyped_image_records(self):
        invalid = [None, [], {}, "Ubuntu release", {**IMAGE, "aliases": "noble"},
                   {**IMAGE, "aliases": [None]}, {**IMAGE, "aliases": [""]}, {**IMAGE, "remote": None}]
        for key in ("os", "release", "version"):
            invalid.extend([{**IMAGE, key: value} for value in (None, 123, "", " ")])
            invalid.append({k: v for k, v in IMAGE.items() if k != key})
        for record in invalid:
            with self.subTest(record=record):
                self.rejected("test4", FIND_STDOUT=json.dumps({"errors": [], "images": {"24.04": IMAGE, "bad": record}}))
        self.rejected("test4", FIND_STDOUT=json.dumps({"errors": [], "images": {" ": IMAGE}}))

    def test_failed_install_prerequisites_emit_core_failures_and_durations(self):
        original = dict(self.values)
        for key in ("steps.install.outcome", "steps.install.outputs.install_status"):
            for state in ("", "failure", "skipped", "cancelled"):
                self.values = {**original, key: state}
                for i in range(1, 6):
                    with self.subTest(key=key, state=state, step=i):
                        self.rejected(f"test{i}")
                        self.assertEqual("", self.calls())

    def test_binary_missing_or_wrong_arch_emits_failure_duration(self):
        (self.bin / "multipass").unlink()
        self.rejected("test1")
        self.rejected("test5", ARCH="x86_64")

    def test_migration_audit_sees_explicit_finalizer_outputs(self):
        for i in range(1, 7):
            step = self.steps[f"test{i}"]
            for key in ("status", "duration"):
                with self.subTest(step=i, key=key):
                    self.assertTrue(observation_audit._step_emits_output(ROOT, step, key))
            self.assertEqual("always()", step["if"])
            if i < 6:
                self.assertTrue(step["continue-on-error"])
                self.assertTrue(step["run"].rstrip().endswith("finish 0"))
        self.assertTrue(observation_audit._step_emits_output(ROOT, self.steps["install"], "install_status"))
        for key in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status"):
            self.assertTrue(observation_audit._step_emits_output(ROOT, self.steps["summary"], key))
        self.assertEqual({("not_applicable_package_manager", "skipped"),
                          ("baseline_failed", "skipped"), ("baseline_install_failed", "skipped")},
                         set(observation_audit._step_literal_pairs(ROOT, self.steps["test6"])))

    def test_summary_checks_raw_outcomes_not_only_passed_labels(self):
        original = dict(self.values)
        for i in range(1, 6):
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(step=i, outcome=outcome):
                    self.values = {**original, f"steps.test{i}.outcome": outcome}
                    result, regression = self.run_step("test6")
                    self.assertEqual("baseline_failed", regression["decision"])
                    self.record("test6", result, regression)
                    result, fields = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("4", "1", "1", "1", "failure", "failing"),
                                     tuple(fields[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status", "badge_status")))

    def test_real_failed_query_propagates_to_summary_and_baseline_decision(self):
        result, fields = self.run_step("test4", FIND_STDOUT="", FIND_STDERR=CERT_ERROR, FIND_RC="7")
        self.record("test4", result, fields)
        result, regression = self.run_step("test6")
        self.record("test6", result, regression)
        self.assertEqual("baseline_failed", regression["decision"])
        result, summary = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        details = [{"name": self.steps[f"test{i}"]["name"],
                    "status": self.values[f"steps.test{i}.outputs.status"]} for i in range(1, 6)]
        details.append({"name": self.steps["test6"]["name"], **regression})
        self.assertEqual("failure", result_policy.validate_six_test_result(
            details=details, passed=int(summary["passed"]), failed=int(summary["failed"]),
            skipped=int(summary["skipped"]), core_failed=int(summary["core_failed"]), decision=regression["decision"]))

    def test_failed_readiness_remains_baseline_install_failure(self):
        result, fields = self.run_step("install", CERT_RC="1")
        self.record("install", result, fields)
        for i in range(1, 6):
            result, fields = self.run_step(f"test{i}")
            self.record(f"test{i}", result, fields)
        result, regression = self.run_step("test6")
        self.record("test6", result, regression)
        self.assertEqual("baseline_install_failed", regression["decision"])
        result, summary = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("0", "5", "1", "5"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))

    def test_snap_install_failure_stops_service_and_fails_all_core_checks(self):
        result, fields = self.run_step("install", SNAP_RC="9")
        self.assertEqual(9, result.returncode)
        self.assertEqual("failed", fields["install_status"])
        self.assertNotIn("systemctl", self.calls())
        self.assertNotIn("sudo test", self.calls())
        self.record("install", result, fields)
        result, fields = self.run_step("version")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("version", fields)
        self.assertEqual("", self.calls())
        for i in range(1, 6):
            result, fields = self.rejected(f"test{i}")
            self.assertEqual("", self.calls())
            self.record(f"test{i}", result, fields)
        result, regression = self.run_step("test6")
        self.assertEqual("baseline_install_failed", regression["decision"])
        self.record("test6", result, regression)
        result, summary = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("0", "5", "1", "5", "failure", "failing"),
                         tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status", "badge_status")))

    def test_missing_version_or_wrong_regression_outcomes_fail_closed(self):
        original = dict(self.values)
        for key, value in (("steps.version.outcome", "failure"), ("steps.version.outputs.version", ""),
                           ("steps.version.outputs.version", "unknown")):
            self.values = {**original, key: value}
            result, regression = self.run_step("test6")
            self.assertEqual("baseline_failed", regression["decision"])
            self.record("test6", result, regression)
            result, fields = self.run_step("summary")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failing", fields["badge_status"])
        for key, value in (("outcome", "failure"), ("outcome", ""), ("outcome", "skipped"),
                           ("outputs.status", "passed"), ("outputs.status", "failed"),
                           ("outputs.decision", "baseline_failed"), ("outputs.decision", "not_configured")):
            self.values = {**original, f"steps.test6.{key}": value}
            result, fields = self.run_step("summary")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(("5", "1", "0", "0"), tuple(fields[k] for k in ("passed", "failed", "skipped", "core_failed")))

    def test_missing_outputs_and_invalid_durations_fail_closed(self):
        original = dict(self.values)
        for i in range(1, 7):
            for duration in ("bad", "-1", "1.5", "1000000"):
                self.values = {**original, f"steps.test{i}.outputs.duration": duration}
                result, fields = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failure", fields["overall_status"])
        self.values = {**original, "steps.test2.outputs.duration": "08"}
        result, fields = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("21", fields["duration"])
        self.values.clear()
        result, fields = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("0", "6", "0", "5"), tuple(fields[k] for k in ("passed", "failed", "skipped", "core_failed")))


if __name__ == "__main__":
    unittest.main()
