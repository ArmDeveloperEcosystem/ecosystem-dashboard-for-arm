"""Synthetic shell fixtures only; these are not native Arm/KVM execution evidence."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-firecraker.yml"
DOCUMENT = yaml.safe_load(WORKFLOW.read_text())
JOB = next(iter(DOCUMENT["jobs"].values()))
STEPS = {step.get("id"): step for step in JOB["steps"] if "id" in step}


class WorkflowFixtures(unittest.TestCase):
    def shell(self, body, extra=None, commands=None):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            output = work / "output"
            output.touch()
            env = dict(os.environ, GITHUB_OUTPUT=str(output), RUNNER_TEMP=tmp)
            env.update(extra or {})
            for name, content in (commands or {}).items():
                path = work / name
                path.write_text(content)
                path.chmod(0o755)
            env["PATH"] = tmp + os.pathsep + env["PATH"]
            result = subprocess.run(
                ["bash", "-c", body], env=env, cwd=ROOT,
                text=True, capture_output=True, timeout=12,
            )
            values = dict(line.split("=", 1) for line in output.read_text().splitlines())
            return result, values

    def summary_env(self):
        env = {"S6": "deferred", "O6": "success", "D6": "0",
               "DECISION": "runtime_validation_not_automated",
               "INSTALL_OUTCOME": "success", "VERSION_OUTCOME": "success"}
        for i in range(1, 6):
            env.update({f"S{i}": "passed", f"O{i}": "success", f"D{i}": "1"})
        return env

    def test_contract(self):
        trigger = DOCUMENT.get("on", DOCUMENT.get(True))
        self.assertIn("workflow_dispatch", trigger)
        self.assertEqual(24, len(trigger["workflow_call"]["outputs"]))
        self.assertEqual(set(JOB["outputs"]), set(trigger["workflow_call"]["outputs"]))
        for i in range(1, 7):
            self.assertTrue(STEPS[f"test{i}"]["continue-on-error"])
        self.assertIn("regression_policy", JOB["outputs"])
        self.assertEqual("applicable", JOB["outputs"]["regression_policy"])
        actions = [step["uses"] for step in JOB["steps"] if "uses" in step]
        self.assertEqual(["actions/checkout@11d5960a326750d5838078e36cf38b85af677262"], actions)

    def test_deferred_not_counted_as_passed(self):
        result, values = self.shell(STEPS["summary"]["run"], self.summary_env())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1", "success"),
                         tuple(values[k] for k in ("passed", "failed", "skipped", "overall_status")))

    def test_missing_failed_or_forged_pass_cannot_turn_green(self):
        faults = [{"S5": ""}, {"O5": "failure"}, {"S5": "failed"},
                  {"S6": ""}, {"O6": "failure"}, {"S6": "passed"},
                  {"DECISION": "not_configured"}, {"INSTALL_OUTCOME": "failure"},
                  {"VERSION_OUTCOME": "failure"}]
        for fault in faults:
            with self.subTest(fault=fault):
                env = self.summary_env()
                env.update(fault)
                result, values = self.shell(STEPS["summary"]["run"], env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failing", values["badge_status"])

    def test_baseline_failure_skips_regression(self):
        env = self.summary_env()
        env["O5"] = "failure"
        result, values = self.shell(STEPS["test6"]["run"], env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("skipped", "baseline_failed"),
                         (values["status"], values["decision"]))


    def test_pipeline_summary_matches_repository_regression_policy(self):
        import sys
        sys.path.insert(0, str(ROOT / ".github/scripts"))
        import package_result_policy as policy

        for fault in ({}, {"S5": "failed", "O5": "failure"},
                      {"INSTALL_OUTCOME": "failure"}, {"VERSION_OUTCOME": "failure"},
                      {"S1": "", "O1": "skipped", "S5": "", "O5": "skipped"}):
            with self.subTest(fault=fault):
                env = self.summary_env()
                env.update(fault)
                regression, evidence = self.shell(STEPS["test6"]["run"], env)
                self.assertEqual(0, regression.returncode, regression.stderr)
                env.update(S6=evidence["status"], O6="success", DECISION=evidence["decision"])
                result, values = self.shell(STEPS["summary"]["run"], env)
                setup_ok = env["INSTALL_OUTCOME"] == env["VERSION_OUTCOME"] == "success"
                statuses = [
                    "passed" if setup_ok and env[f"S{i}"] == "passed" and env[f"O{i}"] == "success"
                    else "failed" for i in range(1, 6)
                ]
                details = [{"name": f"Test {i}", "status": status}
                           for i, status in enumerate(statuses, start=1)]
                details.append({"name": "Test 6", "status": "skipped",
                                "decision": evidence["decision"]})
                required = policy.validate_six_test_result(
                    details=details, passed=int(values["passed"]),
                    failed=int(values["failed"]), skipped=int(values["skipped"]),
                    core_failed=int(values["core_failed"]), decision=evidence["decision"])
                self.assertEqual(required, values["overall_status"])
                self.assertEqual(required == "success", result.returncode == 0)
                semantic = policy.expected_regression_metadata(
                    decision=evidence["decision"], core_failed=int(values["core_failed"]))
                self.assertEqual(semantic["status"], evidence["status"])

    def test_public_caveats_describe_product_not_ci_progress(self):
        page = ROOT / "content/linux/opensource_packages/firecraker.md"
        metadata = yaml.safe_load(page.read_text().split("---", 2)[1])
        caveats = metadata["optional_info"]["support_caveats"].lower()
        for narration in ("smoke", "workflow", "deferred", "test 5", "test 6"):
            self.assertNotIn(narration, caveats)

    def test_version_failure_has_no_invented_version(self):
        tag = JOB["env"]["BASELINE_TAG"]
        for output, rc in [("", 1), ("unparseable", 0), ("WRONG_VERSION", 0),
                           ("Firecracker v9.9.9", 0), ("Firecracker " + tag, 1),
                           (f"Firecracker {tag}\nFirecracker v9.9.9", 0),
                           (f"Firecracker {tag}\nFirecracker {tag}", 0)]:
            with self.subTest(output=output, rc=rc):
                commands = {
                    "timeout": "#!/bin/bash\nshift; shift\nexec \"$@\"\n",
                    "binary": "#!/bin/bash\nprintf '%s\\n' " + shlex.quote(output) + "\nexit " + str(rc) + "\n",
                }
                with tempfile.TemporaryDirectory() as tmp:
                    binary = Path(tmp) / "binary"
                    binary.write_text(commands.pop("binary"))
                    binary.chmod(0o755)
                    result, values = self.shell(STEPS["version"]["run"],
                        {"BINARY": str(binary), "BASELINE_TAG": JOB["env"]["BASELINE_TAG"]}, commands)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("version", values)


    def test_exact_version_is_read_from_actual_output(self):
        tag = JOB["env"]["BASELINE_TAG"]
        for output in ("Firecracker " + tag,
                       f"Firecracker {tag}\n\n2026-10-27 [instance:main] Firecracker exiting successfully. exit_code=0",
                       f"diagnostic before version\nFirecracker {tag}\nnormal exit log"):
            with self.subTest(output=output), tempfile.TemporaryDirectory() as tmp:
                binary = Path(tmp) / "binary"
                binary.write_text("#!/bin/bash\nprintf '%s\\n' " + shlex.quote(output) + "\n")
                binary.chmod(0o755)
                result, values = self.shell(STEPS["version"]["run"],
                    {"BINARY": str(binary), "BASELINE_TAG": tag},
                    {"timeout": "#!/bin/bash\nshift; shift\nexec \"$@\"\n"})
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual(tag, values["version"])

    def test_checksum_mismatch_reports_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            archive.write_bytes(b"corrupted artifact")
            sentinel = Path(tmp) / "jailer-started"
            jailer = Path(tmp) / "jailer"
            jailer.write_text('#!/bin/sh\nprintf started > "$JAILER_SENTINEL"\necho "Jailer $BASELINE_TAG"\n')
            jailer.chmod(0o755)
            result, values = self.shell(STEPS["test3"]["run"],
                {"ARCHIVE": str(archive), "BASELINE_SHA256": "0" * 64,
                 "BASELINE_TAG": JOB["env"]["BASELINE_TAG"],
                 "JAILER": str(jailer), "JAILER_SENTINEL": str(sentinel)},
                {"sha256sum": '''#!/usr/bin/env python3
import hashlib
from pathlib import Path
import sys
assert sys.argv[1:] == ["-c", "-"]
expected, filename = sys.stdin.read().strip().split(None, 1)
valid = hashlib.sha256(Path(filename).read_bytes()).hexdigest() == expected
print(filename + (": OK" if valid else ": FAILED"))
sys.exit(0 if valid else 1)
'''})
            self.assertFalse(sentinel.exists(), "Unverified bundle reached jailer execution")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("FAILED", result.stdout + result.stderr)
        self.assertEqual("failed", values["status"])


class GuestEvidenceFixtures(unittest.TestCase):
    shell = WorkflowFixtures.shell

    def test_generated_initramfs_config_requires_empty_drives(self):
        body = (ROOT / ".github/scripts/tests/firecracker_guest_smoke.sh").read_text()
        generator = body.split('python3 - "$WORK" <<\'PY\'\n', 1)[1].split("\nPY\n", 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "rootfs/bin").mkdir(parents=True)
            (work / "rootfs/bin/sh").write_bytes(b"fixture shell, never executed")
            subprocess.run([sys.executable, "-B", "-c", generator, str(work)], check=True)
            config = json.loads((work / "vm.json").read_text())
            self.assertIn("drives", config)
            self.assertEqual([], config["drives"])
            self.assertEqual(str(work / "smoke-initramfs.cpio"),
                             config["boot-source"]["initrd_path"])
            self.assertEqual(str(work / "vmlinux-6.1.188"),
                             config["boot-source"]["kernel_image_path"])

    def test_guest_log_requires_all_evidence_and_clean_exit(self):
        helper = ROOT / ".github/scripts/tests/firecracker_guest_smoke.sh"
        good = "FIRECRACKER_GUEST_FILE_IO_OK\nFIRECRACKER_GUEST_CHILD_EXIT_37\nFIRECRACKER_GUEST_REBOOT\n"
        cases = [(good, 0, True), (good.replace("\n", "\r\n"), 0, True),
                 (good, 124, False), (good, 1, False),
                 (good.replace("FIRECRACKER_GUEST_FILE_IO_OK", ""), 0, False),
                 (good.replace("FIRECRACKER_GUEST_CHILD_EXIT_37", ""), 0, False),
                 (good.replace("FIRECRACKER_GUEST_REBOOT", ""), 0, False),
                 (good + "Kernel panic - not syncing\n", 0, False),
                 ("Linux booted\n", 0, False)]
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "serial.log"
            for content, code, expected in cases:
                with self.subTest(content=content, code=code):
                    log.write_text(content)
                    result, _ = self.shell(
                        'source "$HELPER"\nvalidate_guest_log "$LOG" "$CODE"',
                        {"HELPER": str(helper), "LOG": str(log), "CODE": str(code)})
                    self.assertEqual(expected, result.returncode == 0, result.stdout + result.stderr)

    def test_kvm_is_mandatory_and_no_api_fallback(self):
        body = (ROOT / ".github/scripts/tests/firecracker_guest_smoke.sh").read_text()
        self.assertIn("[ -c /dev/kvm ]", body)
        self.assertIn("fcntl.ioctl(fd, 0xAE00, 0) == 12", body)
        self.assertIn('return 1', body)
        self.assertIn("--no-api --config-file", body)
        self.assertIn("firecracker_guest_smoke.sh", STEPS["test5"]["run"])
        self.assertNotIn("firecracker_api_smoke.sh", STEPS["test5"]["run"])

    def test_pinned_guest_inputs(self):
        body = (ROOT / ".github/scripts/tests/firecracker_guest_smoke.sh").read_text()
        self.assertIn("20261021-1e5fcc27b59f-0/aarch64", body)
        self.assertIn("8bc7fc7d1eabc0dd7dd8a33cb53b0bb11f25c09d4276757cfe16eb5c8509fa90", body)
        self.assertIn("490be704c18868cde014fbdf4e025a1548bd3efe23bff5086becdf43d6fb05ad", body)
        self.assertIn('sha256sum -c -', body)




FAKE_SERVER = r"""#!/usr/bin/env python3
import json
import os
import socketserver
import sys

fault = os.environ.get("API_FAULT", "")
if fault == "startup":
    sys.exit(1)
config = {"vcpu_count": 1, "mem_size_mib": 128, "smt": False}
args = sys.argv[1:]
assert args[0] == "--api-sock" and len(args) == 2
class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        global config
        method, path, protocol = self.rfile.readline().decode().strip().split()
        headers = {}
        while True:
            line = self.rfile.readline().decode().strip()
            if not line:
                break
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
        body = self.rfile.read(int(headers.get("content-length", 0)))
        status, data = 200, {}
        if path == "/version":
            data = {"firecracker_version": "wrong" if fault == "version" else "1.17.0"}
        elif method == "GET" and path == "/machine-config":
            data = dict(config)
            if fault == "roundtrip" and config["mem_size_mib"] == 256:
                data["mem_size_mib"] = 128
        elif method == "PUT" and path == "/machine-config":
            try:
                parsed = json.loads(body)
                assert parsed["vcpu_count"] > 0
            except (ValueError, KeyError, AssertionError):
                status, data = 400, {"fault_message": "Invalid configuration"}
                if fault == "accept_invalid":
                    status, data = 204, None
                elif fault == "missing_fault":
                    data = {}
                elif fault == "mutate_invalid":
                    config["mem_size_mib"] = 999
            else:
                config = parsed
                status, data = 204, None
        else:
            raise AssertionError((method, path, body))
        if fault == "http_error":
            status = 500
        payload = b"" if data is None else json.dumps(data).encode()
        if fault == "malformed":
            payload = b"{"
        self.wfile.write(
            f"HTTP/1.1 {status} Fixture\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
            + payload
        )
with socketserver.UnixStreamServer(args[1], Handler) as server:
    server.serve_forever()
"""


class ApiFixtures(unittest.TestCase):
    def probe(self, fault):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "firecracker-fixture"
            binary.write_text(FAKE_SERVER)
            binary.chmod(0o755)
            env = dict(os.environ, API_FAULT=fault)
            return subprocess.run(
                ["bash", str(ROOT / ".github/scripts/tests/firecracker_api_smoke.sh"),
                 str(binary), "v1.17.0"],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=12)

    def test_synthetic_api_roundtrip(self):
        result = self.probe("")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("guest boot not tested", result.stdout)

    def test_api_failures_cannot_pass(self):
        for fault in ("startup", "version", "roundtrip", "accept_invalid",
                      "missing_fault", "mutate_invalid", "http_error", "malformed"):
            with self.subTest(fault=fault):
                result = self.probe(fault)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)

if __name__ == "__main__":
    unittest.main()
