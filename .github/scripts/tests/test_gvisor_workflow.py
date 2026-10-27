"""Synthetic shell fixtures only; these are not native Arm/KVM execution evidence."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-gVisor.yml"
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
        page = ROOT / "content/linux/opensource_packages/gVisor.md"
        metadata = yaml.safe_load(page.read_text().split("---", 2)[1])
        caveats = metadata["optional_info"]["support_caveats"].lower()
        for narration in ("smoke", "workflow", "deferred", "test 5", "test 6"):
            self.assertNotIn(narration, caveats)

    def test_version_failure_has_no_invented_version(self):
        for output, rc in [("", 1), ("unparseable", 0), ("WRONG_VERSION", 0)]:
            with self.subTest(output=output, rc=rc):
                commands = {
                    "timeout": "#!/bin/bash\nshift; shift\nexec \"$@\"\n",
                    "binary": "#!/bin/bash\nprintf '%s\\n' " + repr(output) + "\nexit " + str(rc) + "\n",
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
        output = "runsc version " + tag
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "binary"
            binary.write_text("#!/bin/bash\nprintf '%s\\n' " + repr(output) + "\n")
            binary.chmod(0o755)
            result, values = self.shell(STEPS["version"]["run"],
                {"BINARY": str(binary), "BASELINE_TAG": tag},
                {"timeout": "#!/bin/bash\nshift; shift\nexec \"$@\"\n"})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(tag, values["version"])


    def test_rootfs_package_verification_must_succeed_and_be_static(self):
        commands = {
            "uname": "#!/bin/bash\necho aarch64\n",
            "file": "#!/bin/bash\necho 'ELF 64-bit ARM aarch64'\n",
            "dpkg-query": "#!/bin/bash\necho arm64\n",
            "dpkg": "#!/bin/bash\ncase \"$FAULT\" in integrity_error) exit 1;; tampered) echo changed;; esac\n",
            "readelf": "#!/bin/bash\nif [ \"$FAULT\" = dynamic ]; then echo INTERP; fi\nexit 0\n",
        }
        for fault in ("integrity_error", "tampered", "dynamic"):
            with self.subTest(fault=fault):
                result, values = self.shell(STEPS["test4"]["run"],
                    {"BINARY": "/fixture/runsc", "BUSYBOX": "/fixture/busybox", "FAULT": fault},
                    commands)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("failed", values["status"])

    def test_checksum_mismatch_reports_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            archive.write_bytes(b"corrupted artifact")
            result, values = self.shell(STEPS["test3"]["run"],
                {"ARCHIVE": str(archive), "BASELINE_SHA256": "0" * 64})
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", values["status"])


FAKE_RUNSC = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args == ["spec"]:
    Path("config.json").write_text(json.dumps({"root": {}, "process": {}, "linux": {}}))
    sys.exit(0)
if "delete" in args:
    sys.exit(0)
assert "--platform=systrap" in args and "--network=none" in args and "--ignore-cgroups" in args
config = json.loads(Path("config.json").read_text())
assert config["root"] == {"path": "rootfs", "readonly": True}
assert config["process"]["terminal"] is False
assert {x["type"] for x in config["linux"]["namespaces"]} == {"pid", "ipc", "uts", "mount", "network"}
assert any(x["destination"] == "/tmp" and x["type"] == "tmpfs" for x in config["mounts"])
assert not any(x["type"] == "bind" for x in config["mounts"])
assert config["process"]["args"][:3] == ["/bin/busybox", "sh", "-ec"]
fault = os.environ.get("FAULT", "")
if fault == "runtime_failure":
    sys.exit(1)
if fault == "timeout":
    sys.exit(124)
if args[-1] == "dashboard-ok":
    assert "rootfs-must-stay-readonly" in config["process"]["args"][3]
    if fault != "missing_marker":
        print("GVISOR_GUEST_OK")
    sys.exit(0)
assert args[-1] == "dashboard-exit"
assert "exit 37" in config["process"]["args"][3]
if fault != "missing_exit_marker":
    print("GVISOR_EXIT_37")
sys.exit(0 if fault == "wrong_exit" else 37)
"""


class GuestFixtures(unittest.TestCase):
    def probe(self, fault):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            for name, text in {
                "runsc": FAKE_RUNSC,
                "busybox": "#!/bin/sh\nexit 0\n",
                "timeout": "#!/bin/bash\nshift; shift\nexec \"$@\"\n",
                "mountpoint": '#!/bin/sh\ncase "$FAULT" in namespace_mount|cleanup_failure) exit 0;; *) exit 1;; esac\n',
                "umount": '#!/bin/sh\n[ "$FAULT" != cleanup_failure ] || exit 1\necho NAMESPACE_UNMOUNTED\n',
            }.items():
                path = work / name
                path.write_text(text)
                path.chmod(0o755)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"], FAULT=fault)
            return subprocess.run(
                ["bash", str(ROOT / ".github/scripts/tests/gvisor_smoke.sh"),
                 str(work / "runsc"), str(work / "busybox")],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)

    def test_synthetic_guest(self):
        result = self.probe("")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_missing_markers_wrong_exit_or_timeout_fail(self):
        for fault in ("missing_marker", "missing_exit_marker", "wrong_exit", "runtime_failure", "timeout"):
            with self.subTest(fault=fault):
                self.assertNotEqual(0, self.probe(fault).returncode)

    def test_retained_namespace_is_unmounted_before_cleanup(self):
        result = self.probe("namespace_mount")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("NAMESPACE_UNMOUNTED", result.stdout)

    def test_namespace_cleanup_failure_is_not_success(self):
        result = self.probe("cleanup_failure")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
