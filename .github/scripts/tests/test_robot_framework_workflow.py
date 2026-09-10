"""Execute the workflow's version shell against isolated Python installations."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import venv

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as audit


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-robot-framework.yml"
BASH = shutil.which("bash")


class RobotFrameworkWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-robot-framework"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        temporary = tempfile.TemporaryDirectory(prefix="robot-framework-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for command in ("sed", "date"):
            (self.bin / command).symlink_to(shutil.which(command))
        # No host distributions or alternate robot executable may satisfy a fixture.
        venv.EnvBuilder(with_pip=False).create(self.root / "runtime")
        self.python = self.root / "runtime/bin/python"
        self.site = self.root / "site"
        self.module = self.site / "robot"
        self.module.mkdir(parents=True)
        (self.module / "version.py").write_text('''import os
import sys
VERSION = os.environ.get("ROBOT_FIXTURE_MODULE_VERSION", "7.4.2")
def get_full_version(program=None):
    return f"{program} {VERSION} (Python {sys.version.split()[0]} on {sys.platform})"
''')
        (self.module / "__init__.py").write_text('''import os
import sys
from .version import VERSION as __version__, get_full_version
def run_cli():
    if sys.argv[1:] != ["--version", "--nostatusrc"]:
        raise SystemExit("Unexpected CLI arguments")
    sys.stdout.write(os.environ.get("ROBOT_FIXTURE_STDOUT", get_full_version("Robot Framework") + "\\n"))
    sys.stderr.write(os.environ.get("ROBOT_FIXTURE_STDERR", ""))
    return int(os.environ.get("ROBOT_FIXTURE_RC", "0"))
''')
        self.dist = self.site / "robotframework-7.4.2.dist-info"
        self.dist.mkdir()
        self.metadata()
        (self.dist / "entry_points.txt").write_text("[console_scripts]\nrobot = robot:run_cli\n")
        (self.dist / "RECORD").write_text(
            "robot/__init__.py,,\nrobot/version.py,,\n../bin/robot,,\n"
        )
        self.cli = self.bin / "robot"
        self.cli.write_text(f"#!{self.python}\nfrom robot import run_cli\nraise SystemExit(run_cli())\n")
        self.cli.chmod(0o755)
        other_python = self.bin / "python3"
        other_python.write_text("#!/bin/sh\nexit 97\n")
        other_python.chmod(0o755)

    def metadata(self, version="7.4.2", name="robotframework"):
        self.dist.joinpath("METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        )

    def run_step(self, name, expected="7.4.2", **environment):
        step = self.steps[name]
        values = {"steps.version.outputs.version": expected}

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else values.get(term, "")
                if value:
                    return value
            return ""

        def render(source):
            return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)

        output = self.root / "outputs"
        output.write_text("")
        env = dict(os.environ, **self.job.get("env", {}),
                   GITHUB_OUTPUT=str(output), PATH=str(self.bin),
                   PYTHONPATH=str(self.site), PYTHONDONTWRITEBYTECODE="1")
        env.update({key: render(value) for key, value in step.get("env", {}).items()})
        env.update(environment)
        result = subprocess.run([BASH, "-e", "-o", "pipefail", "-c", render(step["run"])],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=25)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def assert_rejected(self, **environment):
        for name in ("version", "test2"):
            with self.subTest(step=name, environment=environment):
                result, outputs = self.run_step(name, **environment)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertNotIn("version", outputs)
                self.assertNotIn("installed_version", outputs)
                if name == "test2":
                    self.assertEqual("failed", outputs.get("status"))
                    self.assertTrue(outputs.get("duration", "").isdigit(), outputs)

    def test_valid_versions_come_from_the_selected_cli_interpreter(self):
        for version in ("7.4.2", "8.0.1", "7.5rc1", "7.5.dev1"):
            with self.subTest(version=version):
                self.metadata(version)
                environment = {"ROBOT_FIXTURE_MODULE_VERSION": version}
                result, outputs = self.run_step("version", **environment)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual({"version": version}, outputs)
                result, outputs = self.run_step("test2", expected=version, **environment)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("passed", outputs["status"])
                self.assertEqual(version, outputs["installed_version"])
                self.assertTrue(outputs["duration"].isdigit())

    def test_test2_rejects_missing_invalid_or_changed_baseline(self):
        for expected in ("", "Framework", "unknown", "7.4.1", "7.4.2\nstatus=passed"):
            with self.subTest(expected=expected):
                result, outputs = self.run_step("test2", expected=expected)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])
                self.assertTrue(outputs["duration"].isdigit())
                self.assertNotIn("installed_version", outputs)

    def test_auditor_sees_test2_status_and_duration(self):
        for output in ("status", "duration"):
            with self.subTest(output=output):
                self.assertTrue(audit._step_emits_output(
                    WORKFLOW.parents[2], self.steps["test2"], output,
                ))

    def test_finalizer_emits_once_and_preserves_success_or_late_failure(self):
        date = self.bin / "date"
        date.unlink()
        date.write_text('#!/bin/sh\nif [ -e "$ROBOT_FIXTURE_CLOCK" ]; then echo 107; '
                        'else : > "$ROBOT_FIXTURE_CLOCK"; echo 100; fi\n')
        date.chmod(0o755)
        clock = self.root / "clock-started"
        original = self.steps["test2"]["run"]
        for code in (0, 37):
            with self.subTest(code=code):
                clock.unlink(missing_ok=True)
                script = original if code == 0 else original.replace("finish 0", "exit 37\nfinish 0")
                self.steps["test2"]["run"] = script + "\nexit 99\n"
                result, outputs = self.run_step("test2", ROBOT_FIXTURE_CLOCK=str(clock))
                self.assertEqual(code, result.returncode, result.stdout + result.stderr)
                status = "passed" if code == 0 else "failed"
                self.assertEqual(status, outputs["status"])
                self.assertEqual("7", outputs["duration"])
                lines = (self.root / "outputs").read_text().splitlines()
                self.assertEqual([f"status={status}"], [line for line in lines if line.startswith("status=")])
                self.assertEqual(["duration=7"], [line for line in lines if line.startswith("duration=")])

    def test_missing_distribution_is_rejected(self):
        shutil.rmtree(self.dist)
        self.assert_rejected()

    def test_wrong_distribution_identity_is_rejected(self):
        self.metadata(name="unrelated")
        self.assert_rejected()

    def test_missing_or_invalid_metadata_version_is_rejected(self):
        for version in ("", "Framework", "unknown", "7", "7.4.2 garbage", "7.4.2\n injected", "7.4.$(true)"):
            with self.subTest(version=version):
                self.metadata(version)
                self.assert_rejected(ROBOT_FIXTURE_MODULE_VERSION=version)
        (self.dist / "METADATA").write_text("Metadata-Version: 2.1\nName: robotframework\n")
        self.assert_rejected()

    def test_package_and_distribution_version_mismatch_is_rejected(self):
        for version in ("7.4.1", "8.0.0", "", "Framework"):
            with self.subTest(version=version):
                self.assert_rejected(ROBOT_FIXTURE_MODULE_VERSION=version)

    def test_missing_package_is_rejected(self):
        shutil.rmtree(self.module)
        self.assert_rejected()

    def test_shadow_package_with_matching_version_is_rejected(self):
        shadow = self.root / "shadow"
        shutil.copytree(self.module, shadow / "robot")
        self.assert_rejected(PYTHONPATH=os.pathsep.join((str(shadow), str(self.site))))

    def test_missing_or_nonexecutable_cli_is_rejected(self):
        self.cli.chmod(0o644)
        self.assert_rejected()
        self.cli.unlink()
        self.assert_rejected()

    def test_foreign_cli_with_matching_banner_is_rejected(self):
        original = self.root / "original-robot"
        self.cli.rename(original)
        self.cli.write_bytes(original.read_bytes())
        self.cli.chmod(0o755)
        (self.dist / "RECORD").write_text(
            "robot/__init__.py,,\nrobot/version.py,,\n../original-robot,,\n"
        )
        self.assert_rejected()

    def test_missing_cli_interpreter_or_shebang_is_rejected(self):
        for shebang in ("", "#!/nonexistent/python", "#!/usr/bin/env python3"):
            with self.subTest(shebang=shebang):
                self.cli.write_text(shebang + "\nexit 0\n")
                self.assert_rejected()

    def test_cli_banner_must_match_package_version_and_runtime_exactly(self):
        for banner in ("", "Robot Framework\n", "Framework\n",
                       "Robot Framework 7.4.1 (Python 3.12.3 on linux)\n",
                       "Robot Framework 7.4.2 (Python 0.0.0 on unrelated)\n",
                       "unrelated Robot Framework 7.4.2\n", "7.4.2\n"):
            with self.subTest(banner=banner):
                self.assert_rejected(ROBOT_FIXTURE_STDOUT=banner)
        self.cli.write_text(self.cli.read_text().replace(
            "raise SystemExit(run_cli())", "run_cli()\nprint('status=passed')"
        ))
        self.assert_rejected()

    def test_failed_cli_with_valid_banner_is_rejected(self):
        for code in (1, 23, 251):
            with self.subTest(code=code):
                self.assert_rejected(ROBOT_FIXTURE_RC=str(code))

    def test_cli_stderr_is_not_accepted_as_clean_identity(self):
        self.assert_rejected(ROBOT_FIXTURE_STDERR="CLI diagnostic\n")

    def test_missing_or_wrong_entry_point_is_rejected(self):
        path = self.dist / "entry_points.txt"
        for contents in ("", "[console_scripts]\nrobot = robot:unrelated\n",
                         "[console_scripts]\nother = robot:run_cli\n"):
            with self.subTest(contents=contents):
                path.write_text(contents)
                self.assert_rejected()

    def test_missing_installation_file_records_are_rejected(self):
        record = self.dist / "RECORD"
        for contents in ("", "robot/__init__.py,,\n", "../bin/robot,,\n"):
            with self.subTest(contents=contents):
                record.write_text(contents)
                self.assert_rejected()
        record.unlink()
        self.assert_rejected()

    def test_invalid_or_failed_probe_output_is_never_exported(self):
        interpreter = self.root / "probe-interpreter"
        self.cli.write_text(f"#!{interpreter}\n")
        for output, code in (("", 0), ("Framework", 0), ("unknown", 0),
                             ("7.4.2\nstatus=passed", 0), ("7.4.2", 29)):
            with self.subTest(output=output, code=code):
                interpreter.write_text("#!/bin/sh\nprintf '%s\\n' " + shlex.quote(output)
                                       + f"\nexit {code}\n")
                interpreter.chmod(0o755)
                self.assert_rejected()

    def test_test5_still_runs_the_real_robot_arithmetic_suite(self):
        script = self.steps["test5"]["run"]
        self.assertIn("Evaluate    1 + 1", script)
        self.assertIn("Should Be Equal As Integers", script)
        self.assertIn("if robot --outputdir results smoke_test.robot; then", script)
        self.assertNotIn("status=skipped", script)

    def test_package_manager_regression_classification_is_preserved(self):
        result, outputs = self.run_step("test6", expected="7.4.2")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("7.4.2", outputs["current_version"])
        self.assertEqual("not_applicable_package_manager", outputs["decision"])
        self.assertEqual("skipped", outputs["status"])
        self.assertEqual("not_applicable", outputs["latest_version"])
        self.assertEqual("not_applicable", outputs["next_installed_version"])
        self.assertEqual("0", outputs["duration"])


if __name__ == "__main__":
    unittest.main()
