"""Execute LZO workflow shells with controlled CLIs, not a simulated native pass."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

from test_notary_workflow import PMDecisionChecks

WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-LZO.yml"


class LzoWorkflowTests(PMDecisionChecks, unittest.TestCase):
    workflow = WORKFLOW

    def pm_run_step(self, name, values):
        return self.run_step(name, values)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="lzo-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.steps = {step["id"]: step for step in
                      yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-lzo"]["steps"] if "id" in step}
        for name, path in (("python3", sys.executable), ("date", shutil.which("date")), ("grep", shutil.which("grep"))):
            (self.bin / name).symlink_to(path)
        self.env = dict(os.environ, PATH=str(self.bin), GITHUB_OUTPUT=str(self.root / "output"),
                        BANNER="lzop 1.04\nLZO library 2.10\nCopyright holder\n",
                        LZOP_ROW="lzop\tinstall ok installed\t1.04-2build3\tarm64\t1.04\n",
                        LIB_ROW="liblzo2-2\tinstall ok installed\t2.10-2build4\tarm64\t2.10\n",
                        CALL_LOG=str(self.root / "calls"))
        self.stub("uname", 'import os\nprint(os.environ.get("ARCH", "aarch64"))\n')
        self.stub("dpkg-query", r'''
import os
import sys
if sys.argv[1] == "-W":
    assert sys.argv[2] == "-f=${Package}\t${Status}\t${Version}\t${Architecture}\t${source:Upstream-Version}\n"
    key = {"lzop": "LZOP_ROW", "liblzo2-2": "LIB_ROW"}[sys.argv[3]]
    print(os.environ[key], end="")
elif sys.argv[1:] == ["-L", "lzop"]:
    print(os.environ.get("OWNED", __file__.replace("dpkg-query", "lzop")))
else:
    raise RuntimeError(sys.argv)
sys.exit(int(os.environ.get("PKG_RC", "0")))
''')
        self.stub("sudo", 'import os, shutil, sys\nos.execv(shutil.which(sys.argv[1]), sys.argv[1:])\n')
        self.stub("apt-get", 'import os, sys\nsys.exit(int(os.environ.get("UPDATE_RC" if sys.argv[1] == "update" else "INSTALL_RC", "0")))\n')
        self.stub("lzop", r'''
import os
import sys
args = sys.argv[1:]
if args == ["--version"]:
    print(os.environ["BANNER"], end="")
    print(os.environ.get("CLI_STDERR", ""), end="", file=sys.stderr)
    sys.exit(int(os.environ.get("CLI_RC", "0")))
if args == ["--help"]:
    print("Usage: lzop [OPTIONS]")
    sys.exit(int(os.environ.get("HELP_RC", "0")))
data = sys.stdin.buffer.read()
with open(os.environ["CALL_LOG"], "a") as output:
    output.write(f"{args!r} {len(data)}\n")
if args == ["-c"]:
    output = b"LZO-fixture:" + data
    if os.environ.get("EMPTY_COMPRESSED"):
        output = b""
    phase = "COMPRESS"
elif args == ["-d", "-c"]:
    assert data.startswith(b"LZO-fixture:")
    output = data[len(b"LZO-fixture:"):]
    if os.environ.get("WRONG_RESULT"):
        output += b"wrong"
    phase = "DECOMPRESS"
else:
    raise RuntimeError(args)
sys.stdout.buffer.write(output)
print(os.environ.get(phase + "_STDERR", ""), end="", file=sys.stderr)
sys.exit(int(os.environ.get(phase + "_RC", "0")))
''')

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def verified(self):
        return {"steps.version.outputs.status": "passed", "steps.version.outputs.version": "2.10",
                "steps.version.outputs.wrapper_version": "1.04",
                "steps.version.outputs.binary": str(self.bin / "lzop")}

    def run_step(self, name, values=None, source=None, **env):
        values = self.verified() if values is None else values

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
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        step_env = {key: render(value) for key, value in step.get("env", {}).items()}
        result = subprocess.run(["/bin/bash", "-e", "-c", render(source or step["run"])],
                                cwd=self.root, env={**self.env, **step_env, **env},
                                capture_output=True, text=True, timeout=20)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(line) == 2 for line in lines), lines)
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate terminal output keys")
        return result, outputs

    def rejected(self, name, values=None, **env):
        result, output = self.run_step(name, values, **env)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["status"], "failed")
        if name in ("version", "test2", "test5"):
            self.assertRegex(output["duration"], r"^[0-9]+$")
        if name == "version":
            self.assertNotIn("version", output)
        return result, output

    def test_install_failure_cannot_be_skipped_or_succeed(self):
        result, output = self.run_step("install", INSTALL_RC="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.get("install_status"), "failed")

    def test_version_is_library_identity_not_wrapper(self):
        result, output = self.run_step("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["version"], "2.10")
        self.assertEqual(output["wrapper_version"], "1.04")
        self.assertEqual(output["binary"], str(self.bin / "lzop"))
        self.assertEqual(output["status"], "passed")

    def test_valid_future_library_version_is_not_hardcoded(self):
        result, output = self.run_step("version", LIB_ROW=self.env["LIB_ROW"].replace("2.10", "2.11"),
                                       BANNER=self.env["BANNER"].replace("2.10", "2.11"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["version"], "2.11")

    def test_missing_malformed_wrong_product_and_swapped_banners_fail(self):
        for banner in ("", "lzop 1.04\n", "2.10\n", "LZO library 2.10\nlzop 1.04\n",
                       self.env["BANNER"].replace("LZO library", "Other library"),
                       self.env["BANNER"].replace("2.10", "1.04"),
                       self.env["BANNER"].replace("lzop 1.04", "lzop 2.10"),
                       "Usage: lzop\n" + self.env["BANNER"], self.env["BANNER"] * 2,
                       self.env["BANNER"] + "LZO library 2.11\n"):
            with self.subTest(banner=banner):
                self.rejected("version", BANNER=banner)

    def test_failed_identity_commands_and_diagnostics_do_not_emit_version(self):
        for env in ({"CLI_RC": "1"}, {"CLI_STDERR": "warning\n"}, {"PKG_RC": "1"}):
            with self.subTest(env=env):
                self.rejected("version", **env)

    def test_package_identity_architecture_revision_and_ownership_must_match(self):
        for key in ("LIB_ROW", "LZOP_ROW"):
            row = self.env[key]
            for invalid in ("", row * 2, row.replace("arm64", "amd64"),
                            row.replace("install ok installed", "deinstall ok config-files"),
                            row.replace("2.10-2build4", "2.11-2build4") if key == "LIB_ROW" else row.replace("1.04-2build3", "1.05-2build3")):
                with self.subTest(key=key, invalid=invalid):
                    self.rejected("version", **{key: invalid})
        self.rejected("version", OWNED="/not-the-binary")
        (self.bin / "lzop").unlink()
        self.rejected("version")

    def test_test2_rejects_missing_or_changed_library_and_wrapper_identity(self):
        result, output = self.run_step("test2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["status"], "passed")
        for key in self.verified():
            values = self.verified()
            values[key] = ""
            self.rejected("test2", values)
        self.rejected("test2", BANNER=self.env["BANNER"].replace("2.10", "2.11"))
        self.rejected("test2", CLI_RC="1")
        self.rejected("test2", CLI_STDERR="diagnostic\n")

    def test_roundtrip_executes_empty_repeated_and_binary_cases(self):
        result, output = self.run_step("test5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["status"], "passed")
        self.assertEqual(len((self.root / "calls").read_text().splitlines()), 6)
        for size in (0, 73728, 65792):
            self.assertIn(f"{size} bytes roundtripped", result.stdout)

    def test_roundtrip_rejects_failed_commands_diagnostics_empty_and_wrong_data(self):
        for env in ({"COMPRESS_RC": "1"}, {"DECOMPRESS_RC": "1"}, {"COMPRESS_STDERR": "warn"},
                    {"DECOMPRESS_STDERR": "warn"}, {"EMPTY_COMPRESSED": "1"}, {"WRONG_RESULT": "1"}):
            with self.subTest(env=env):
                self.rejected("test5", **env)

    def test_wrong_architecture_or_unverified_version_prevents_runtime_pass(self):
        self.rejected("test5", ARCH="x86_64")
        values = self.verified()
        values["steps.version.outputs.status"] = "failed"
        self.rejected("test5", values)

    def test_matching_help_text_cannot_hide_command_failure(self):
        result, output = self.run_step("test3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["status"], "passed")
        self.rejected("test3", HELP_RC="1")

    def summary_values(self):
        values = self.verified()
        values.update({"steps.install.outcome": "success", "steps.version.outcome": "success"})
        for index in range(1, 6):
            values.update({f"steps.test{index}.outputs.status": "passed",
                           f"steps.test{index}.outputs.duration": "2", f"steps.test{index}.outcome": "success"})
        values.update({"steps.test6.outputs.status": "skipped", "steps.test6.outcome": "success",
                       "steps.test6.outputs.decision": "not_applicable_package_manager",
                       "steps.test6.outputs.duration": "0"})
        return values

    def test_complete_summary_is_five_passes_and_one_real_package_manager_skip(self):
        result, output = self.run_step("summary", self.summary_values())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(output, {"passed": "5", "failed": "0", "core_failed": "0", "skipped": "1",
                                  "duration": "10", "overall_status": "success", "badge_status": "passing"})
        result, output = self.run_step("test6", self.summary_values())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(output["status"], "skipped")
        self.assertEqual(output["decision"], "not_applicable_package_manager")

    def test_failed_missing_or_contradictory_core_outcomes_produce_red_summary(self):
        for index in range(1, 6):
            for field, invalid in (("outputs.status", "failed"), ("outputs.status", ""),
                                   ("outcome", "failure"), ("outcome", "")):
                values = self.summary_values()
                values[f"steps.test{index}.{field}"] = invalid
                self.pm_guard(values)
                result, output = self.run_step("summary", values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((output["passed"], output["failed"], output["core_failed"], output["duration"]),
                                 ("4", "1", "1", "10"))
                self.assertEqual(output["badge_status"], "failing")

    def test_invalid_regression_outcome_status_or_decision_cannot_be_a_skip(self):
        for field, invalid in (("outcome", "failure"), ("outcome", ""), ("outputs.status", "passed"),
                               ("outputs.status", ""), ("outputs.decision", "baseline_failed"), ("outputs.decision", "")):
            values = self.summary_values()
            values[f"steps.test6.{field}"] = invalid
            result, output = self.run_step("summary", values)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((output["passed"], output["failed"], output["skipped"], output["core_failed"]),
                             ("5", "1", "0", "0"))
            self.assertEqual(output["badge_status"], "failing")

    def test_actual_auditor_sees_explicit_status_and_duration(self):
        scripts = str(WORKFLOW.parents[1] / "scripts")
        sys.path.insert(0, scripts)
        self.addCleanup(sys.path.remove, scripts)
        import package_observation_migration_audit as audit
        for name in ("version", "test2", "test5"):
            for field in ("status", "duration"):
                self.assertTrue(audit._step_emits_output(WORKFLOW.parents[2], self.steps[name], field), (name, field))

    def test_late_failure_emits_failed_status_once_and_preserves_exit(self):
        source = self.steps["test5"]["run"].rsplit("finish 0", 1)[0] + "exit 37\n"
        result, output = self.run_step("test5", source=source)
        self.assertEqual(result.returncode, 37)
        self.assertEqual(output["status"], "failed")
        self.assertRegex(output["duration"], r"^[0-9]+$")


if __name__ == "__main__":
    unittest.main()
