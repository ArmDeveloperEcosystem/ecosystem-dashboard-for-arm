"""Exercise Samba's source trust, protocol probes, and output contract offline."""

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
FINGERPRINT = "81F5E2832BD2545A1897B713AA99442FB680B620"
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
        self.base_tree = self.root / f"samba-{BASELINE}"
        self.base_tree.mkdir()
        self.base_tar = self.root / f"samba-{BASELINE}.tar"
        self.base_signature = self.root / f"samba-{BASELINE}.tar.asc"
        self.base_gnupghome = self.root / "gnupg"
        self.base_tar.write_bytes(b"offline baseline tar fixture")
        self.base_signature.write_text("offline signature fixture")
        self.base_gnupghome.mkdir(mode=0o700)
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
                "steps.install.outcome": "success",
                "steps.version.outcome": "success",
                "steps.test6.outputs.decision": "next_install_validated",
                "steps.install.outputs.base_tar": str(self.base_tar),
                "steps.install.outputs.base_signature": str(self.base_signature),
                "steps.install.outputs.base_gnupghome": str(self.base_gnupghome),
            }
        )
        self.stub(
            "curl",
            r'''
import os
from pathlib import Path
import sys

args = sys.argv[1:]
url = args[-1]
with open(os.environ["TRACE"], "a") as trace:
    trace.write("curl " + url + "\n")
if os.environ.get("FAIL_STAGE") == "download":
    raise SystemExit(22)
target = Path(args[args.index("-o") + 1])
target.parent.mkdir(parents=True, exist_ok=True)
if url.rstrip("/").endswith("/stable"):
    target.write_text(
        os.environ.get(
            "INDEX_FIXTURE",
            '<a href="samba-4.23.6.tar.gz">baseline</a>'
            '<a href="samba-4.23.7.tar.gz">candidate</a>',
        )
    )
else:
    target.write_bytes(b"offline Samba download fixture")
''',
        )
        self.stub(
            "gzip",
            r'''
import os
import sys

with open(os.environ["TRACE"], "a") as trace:
    trace.write("gzip " + " ".join(sys.argv[1:]) + "\n")
sys.stdout.buffer.write(b"offline uncompressed Samba tar fixture")
''',
        )
        self.stub(
            "gpg",
            r'''
import os
import sys

fingerprint = os.environ["SAMBA_RELEASE_FINGERPRINT"]
args = sys.argv[1:]
with open(os.environ["TRACE"], "a") as trace:
    trace.write("gpg " + " ".join(args) + "\n")
if "--fingerprint" in args:
    if os.environ.get("FAIL_STAGE") == "fingerprint":
        fingerprint = "0" * 40
    print("fpr:::::::::" + fingerprint + ":")
elif "--verify" in args:
    if os.environ.get("FAIL_STAGE") == "signature":
        raise SystemExit(1)
    print("[GNUPG:] VALIDSIG " + fingerprint + " 2026-01-01 0 4 0 1 10 00 " + fingerprint)
''',
        )
        self.stub(
            "tar",
            r'''
import os
from pathlib import Path
import sys

with open(os.environ["TRACE"], "a") as trace:
    trace.write("tar " + " ".join(sys.argv[1:]) + "\n")
args = sys.argv[1:]
destination = Path(args[args.index("-C") + 1])
source = next(Path(arg) for arg in args if arg.endswith(".tar"))
version = source.name.removeprefix("samba-").removesuffix(".tar")
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
binary_dir = Path.cwd() / "bin"
binary_dir.mkdir(parents=True, exist_ok=True)
built_version = Path.cwd().name.removeprefix("samba-")
client = binary_dir / "smbclient"
client.write_text(
    "#!" + sys.executable + "\n"
    "import os, shlex, sys\n"
    "from pathlib import Path\n"
    "args = sys.argv[1:]\n"
    "with open(os.environ['TRACE'], 'a') as trace:\n"
    "    trace.write('smbclient ' + ' '.join(args) + '\\n')\n"
    "if '--version' in args:\n"
    "    print('Version " + built_version + "')\n"
    "elif '-L' in args:\n"
    "    import time\n"
    "    if os.environ.get('FAIL_STAGE') == 'probe-list': raise SystemExit(1)\n"
    "    for _ in range(100):\n"
    "        if 'smbd-start' in Path(os.environ['TRACE']).read_text(): break\n"
    "        time.sleep(0.01)\n"
    "    else: raise SystemExit(1)\n"
    "    print('        smoke        Disk')\n"
    "elif '-c' in args:\n"
    "    if os.environ.get('FAIL_STAGE') == 'probe-read': raise SystemExit(1)\n"
    "    command = shlex.split(args[args.index('-c') + 1])\n"
    "    destination = Path(command[-1])\n"
    "    label = 'candidate' if 'candidate-probe' in str(destination) else 'baseline'\n"
    "    destination.write_text('samba-' + label + '-protocol-ok\\n')\n"
    "else:\n"
    "    raise SystemExit(2)\n"
)
client.chmod(0o755)
server = binary_dir / "smbd"
server.write_text(
    "#!/bin/bash\n"
    "echo smbd-start >> \"$TRACE\"\n"
    "if [ \"${FAIL_STAGE:-}\" = server-start ]; then exit 7; fi\n"
    "if [ \"${FAIL_STAGE:-}\" = cleanup ]; then\n"
    "    trap '' TERM\n"
    "else\n"
    "    trap 'echo smbd-cleanup >> \"$TRACE\"; exit 0' TERM INT\n"
    "fi\n"
    "while :; do sleep 1; done\n"
)
server.chmod(0o755)
''',
        )
        self.stub(
            "setsid",
            r'''
import os
import sys

with open(os.environ["TRACE"], "a") as trace:
    trace.write("setsid " + " ".join(sys.argv[1:]) + "\n")
os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
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
        self.stub(
            "uname",
            r'''
print("aarch64")
''',
        )
        self.stub(
            "file",
            r'''
import sys

print(f"{sys.argv[-1]}: ELF 64-bit LSB pie executable, ARM aarch64")
''',
        )
        subprocess.run(
            [str(self.bin / "make"), "bin/smbclient", "bin/smbd"],
            cwd=self.base_tree,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        )
        self.values["steps.install.outputs.base_bin"] = str(
            self.base_tree / "bin/smbclient"
        )
        self.values["steps.install.outputs.base_smbd"] = str(
            self.base_tree / "bin/smbd"
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
            timeout=20,
        )
        fields = dict(
            line.split("=", 1)
            for line in self.output.read_text().splitlines()
            if "=" in line
        )
        return result, fields

    def assert_complete_regression(self, fields, current=BASELINE):
        self.assertTrue(
            REGRESSION_OUTPUTS.issubset(fields),
            f"missing outputs: {sorted(REGRESSION_OUTPUTS - fields.keys())}; got {fields}",
        )
        self.assertEqual(current, fields["current_version"])
        self.assertRegex(fields["duration"], r"^[0-9]+$")
        self.assertTrue(fields["regression_result"])
        self.assertTrue(fields["comparison"])

    def assert_no_probe_directory(self, label):
        self.assertEqual([], list(self.root.glob(f"samba-{label}-probe.*")))

    def test_signature_policy_pins_official_key_and_uncompressed_tar(self):
        workflow = WORKFLOW.read_text()
        install = self.steps["install"]["run"]
        test3 = self.steps["test3"]["run"]
        self.assertEqual(FINGERPRINT, self.job["env"]["SAMBA_RELEASE_FINGERPRINT"])
        self.assertIn("gnupg", install)
        self.assertIn("https://download.samba.org/pub/samba/samba-pubkey.asc", install)
        self.assertIn("samba-${SAMBA_VERSION}.tar.asc", install)
        self.assertIn('gzip -dc "$BASE_ARCHIVE" > "$BASE_TAR"', install)
        self.assertIn('--verify "$BASE_SIGNATURE" "$BASE_TAR"', install)
        self.assertIn("VALIDSIG ${SAMBA_RELEASE_FINGERPRINT}", install)
        self.assertIn('--verify "$BASE_SIGNATURE" "$BASE_TAR"', test3)
        self.assertNotIn("Connection to localhost failed", workflow)
        self.assertEqual(180, self.job["timeout-minutes"])

    def test_release_index_must_contain_the_pinned_baseline(self):
        result, fields = self.run_step("version", INDEX_FIXTURE="<html></html>")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", fields["lookup_status"])
        self.assertEqual("", fields["latest"])

        result, fields = self.run_step(
            "version",
            INDEX_FIXTURE='<a href="samba-4.23.6.tar.gz">baseline</a>',
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("no_newer_stable", fields["lookup_status"])
        self.assertEqual("", fields["latest"])

    def test_baseline_signature_step_accepts_only_pinned_fingerprint(self):
        result, fields = self.run_step("test3")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", fields["status"])
        self.assertIn("--verify", self.trace.read_text())

        result, fields = self.run_step("test3", FAIL_STAGE="fingerprint")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", fields["status"])

    def test_baseline_build_and_protocol_probe_require_client_and_server(self):
        install = self.steps["install"]["run"]
        architecture = self.steps["test4"]["run"]
        test5 = self.steps["test5"]["run"]
        self.assertIn("make -j2 bin/smbclient bin/smbd", install)
        self.assertIn('BASE_SMBD="${{ steps.install.outputs.base_smbd }}"', architecture)
        self.assertIn('file -L "${BASE_REAL_BIN}"', architecture)
        self.assertIn('file -L "${BASE_REAL_SMBD}"', architecture)
        self.assertIn('BASE_SMBD="${{ steps.install.outputs.base_smbd }}"', test5)
        self.assertIn("bind interfaces only = yes", test5)
        self.assertIn("smb ports = $smb_port", test5)
        self.assertIn("guest ok = yes", test5)
        self.assertIn("read only = yes", test5)
        self.assertIn("-L 127.0.0.1", test5)
        self.assertIn("get marker.txt $downloaded_marker", test5)
        self.assertIn('cmp -s "$share_dir/marker.txt" "$downloaded_marker"', test5)
        self.assertIn("cleanup_probe_success", test5)
        self.assertIn('kill -TERM -- "-$smbd_pid"', test5)
        self.assertIn('if kill -0 "$smbd_pid"', test5)
        self.assertIn('if [ -e "$probe_root" ]', test5)

        result, fields = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", fields["status"])
        trace = self.trace.read_text()
        self.assertIn("smbd-start", trace)
        self.assertIn("smbclient -L 127.0.0.1", trace)
        self.assertIn("get marker.txt", trace)
        self.assertIn("smbd-cleanup", trace)
        self.assert_no_probe_directory("baseline")

    def test_protocol_failure_is_not_accepted_and_cleanup_still_runs(self):
        result, fields = self.run_step("test5", FAIL_STAGE="probe-read")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", fields["status"])
        trace = self.trace.read_text()
        self.assertIn("get marker.txt", trace)
        self.assertIn("smbd-cleanup", trace)
        self.assert_no_probe_directory("baseline")

    def test_graceful_cleanup_failure_fails_the_probe(self):
        result, fields = self.run_step("test5", FAIL_STAGE="cleanup")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", fields["status"])
        self.assertIn("smbd-start", self.trace.read_text())
        self.assert_no_probe_directory("baseline")

    def test_candidate_signature_build_and_protocol_probe_validate(self):
        test6 = self.steps["test6"]["run"]
        self.assertIn('samba-${LATEST}.tar.asc', test6)
        self.assertIn('--verify "$NEXT_SIGNATURE" "$NEXT_TAR"', test6)
        self.assertIn("make -j2 bin/smbclient bin/smbd", test6)
        self.assertIn('file -L "$NEXT_REAL_BIN"', test6)
        self.assertIn('file -L "$NEXT_REAL_SMBD"', test6)
        self.assertIn('run_protocol_probe "$NEXT_BIN" "$NEXT_SMBD" candidate 14446', test6)
        self.assertIn("cleanup_probe_success", test6)

        result, fields = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_complete_regression(fields)
        self.assertEqual(CANDIDATE, fields["next_installed_version"])
        self.assertEqual("passed", fields["status"])
        self.assertEqual("next_install_validated", fields["decision"])
        trace = self.trace.read_text()
        self.assertIn("gpg --batch --status-fd 1 --verify", trace)
        self.assertIn("make -j2 bin/smbclient bin/smbd", trace)
        self.assertIn("smbd-start", trace)
        self.assertIn("get marker.txt", trace)
        self.assertIn("smbd-cleanup", trace)
        self.assert_no_probe_directory("candidate")

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

    def test_baseline_failure_skips_candidate_with_explicit_decision(self):
        self.assertEqual("always()", self.steps["test6"]["if"])
        result, fields = self.run_step(
            "test6",
            {
                "steps.test3.outputs.status": "failed",
                "steps.test3.outcome": "failure",
            },
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_complete_regression(fields)
        self.assertEqual("skipped", fields["status"])
        self.assertEqual("baseline_failed", fields["decision"])
        self.assertEqual("not_installed", fields["next_installed_version"])
        self.assertEqual("", self.trace.read_text())

    def test_install_and_version_failures_emit_baseline_decisions(self):
        cases = (
            (
                {
                    "steps.install.outcome": "failure",
                    "steps.version.outcome": "skipped",
                    "steps.version.outputs.version": "",
                    "steps.version.outputs.latest": "",
                    "steps.version.outputs.lookup_status": "",
                },
                "baseline_install_failed",
            ),
            (
                {
                    "steps.version.outcome": "failure",
                    "steps.version.outputs.version": "",
                    "steps.version.outputs.latest": "",
                    "steps.version.outputs.lookup_status": "failed",
                },
                "baseline_failed",
            ),
        )
        for values, expected_decision in cases:
            with self.subTest(decision=expected_decision):
                result, fields = self.run_step("test6", values)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assert_complete_regression(fields, current="unknown")
                self.assertEqual("skipped", fields["status"])
                self.assertEqual(expected_decision, fields["decision"])
                self.assertEqual("not_installed", fields["next_installed_version"])
                self.assertEqual("unknown", fields["current_version"])
                self.assertEqual("", self.trace.read_text())

    def test_candidate_failures_emit_complete_failed_results_and_cleanup(self):
        for stage in ("download", "signature", "build", "probe-read"):
            with self.subTest(stage=stage):
                result, fields = self.run_step("test6", FAIL_STAGE=stage)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assert_complete_regression(fields)
                self.assertEqual(CANDIDATE, fields["latest_version"])
                self.assertEqual("failed", fields["status"])
                self.assertEqual("next_install_failed", fields["decision"])
                trace = self.trace.read_text()
                self.assertIn("curl ", trace)
                self.assertEqual(stage in ("build", "probe-read"), "make " in trace)
                if stage == "probe-read":
                    self.assertEqual(CANDIDATE, fields["next_installed_version"])
                    self.assertIn("smbd-cleanup", trace)
                else:
                    self.assertEqual("not_installed", fields["next_installed_version"])
                self.assert_no_probe_directory("candidate")

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
        self.assertEqual("not_installed", fields["next_installed_version"])
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
        self.assertEqual(
            "${{ steps.summary.outputs.overall_status || 'failure' }}",
            self.job["outputs"]["run_status"],
        )
        self.assertEqual(
            "${{ steps.summary.outputs.badge_status || 'failing' }}",
            self.job["outputs"]["badge_status"],
        )

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

    def test_summary_accepts_baseline_failed_only_with_core_failure(self):
        result, fields = self.run_step(
            "summary",
            {
                "steps.test3.outputs.status": "failed",
                "steps.test3.outcome": "failure",
                "steps.test6.outputs.status": "skipped",
                "steps.test6.outputs.decision": "baseline_failed",
                "steps.test6.outcome": "success",
            },
        )
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(SUMMARY_OUTPUTS, set(fields))
        self.assertEqual("1", fields["core_failed"])
        self.assertEqual("1", fields["failed"])
        self.assertEqual("1", fields["skipped"])
        self.assertEqual("failure", fields["overall_status"])
        self.assertEqual("failing", fields["badge_status"])


if __name__ == "__main__":
    unittest.main()
