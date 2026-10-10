"""Exercise Backstage workflow shell with fault fixtures, not Arm product evidence."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-backstage.yml"


class BackstageWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="backstage-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runner_temp = self.root / "runner temp"
        self.runner_temp.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-backstage"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = {
            **os.environ,
            "HOME": str(self.root),
            "RUNNER_TEMP": str(self.runner_temp),
            "BACKSTAGE_PREFIX": self.steps["install"]["env"]["BACKSTAGE_PREFIX"].replace(
                "${{ runner.temp }}", str(self.runner_temp)),
            "BACKSTAGE_INSTALL_MANIFEST": self.steps["install"]["env"]["BACKSTAGE_INSTALL_MANIFEST"],
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "GITHUB_OUTPUT": str(self.root / "output"),
            "GITHUB_PATH": str(self.root / "path"),
            "CLI_RC": "0", "CLI_STDOUT": "0.36.6", "CLI_STDERR": "",
            "NPM_RC": "0", "NPM_BINARY": "1", "NPM_LOG": "1",
            "NODE_RC": "0", "INSTALLED_VERSION": "0.36.6", "TEST_ARCH": "aarch64",
            "YARN_RC": "0",
        }
        self.tool("sudo", "echo 'Unexpected sudo' >&2\nexit 98\n")
        self.tool("uname", 'printf "%s\\n" "$TEST_ARCH"\n')
        self.tool("yarn", '''
printf '%s:%s\\n' "$PWD" "$*" >> "$HOME/yarn-calls"
exit "$YARN_RC"
''')
        self.tool("node", '''
if [ "$1" = --version ]; then echo v24.0.0; exit 0; fi
printf '%s\\n' "$*" >> "$HOME/node-calls"
printf '%s\\n' "$INSTALLED_VERSION"
exit "$NODE_RC"
''')
        self.tool("backstage-cli", '''
printf '%s\\n' "$*" >> "$HOME/cli-calls"
printf '%s\\n' "$CLI_STDOUT"
printf '%s' "$CLI_STDERR" >&2
exit "$CLI_RC"
''')
        self.tool("npm", '''
if [ "$1" = --version ]; then echo 11.0.0; exit 0; fi
printf '%s\\n' "$@" > "$HOME/npm-args"
test -f "$BACKSTAGE_PREFIX/package.json"
if [ "$NPM_LOG" = 1 ]; then
  printf '%s\\n' 'fixture npm failure details' > "$RUNNER_TEMP/backstage-npm-logs/unit-debug-0.log"
fi
if [ "$NPM_RC" != 0 ]; then exit "$NPM_RC"; fi
if [ "$NPM_BINARY" = 1 ]; then
  mkdir -p "$BACKSTAGE_PREFIX/node_modules/.bin"
  cp "$HOME/bin/backstage-cli" "$BACKSTAGE_PREFIX/node_modules/.bin/backstage-cli"
fi
''')

    def tool(self, name, source):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + source)
        path.chmod(0o755)

    def render(self, source, values=None):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if (values or {}).get(term):
                    return values[term]
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)

    def run_step(self, name, values=None, **environment):
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        Path(self.env["GITHUB_PATH"]).write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.render(self.steps[name]["run"], values)],
            cwd=self.root, env={**self.env, **environment}, capture_output=True,
            text=True, timeout=15)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate workflow outputs")
        return result, outputs

    def test_supported_node_and_all_existing_runtime_checks_remain(self):
        setup = next(step for step in self.job["steps"] if step["name"] == "Setup Node.js")
        self.assertEqual("24", setup["with"]["node-version"])
        self.assertEqual(10, self.steps["install"]["timeout-minutes"])
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual(self.steps["install"]["env"]["BACKSTAGE_PREFIX"],
                         self.steps["version"]["env"]["BACKSTAGE_PREFIX"])
        for number, command in enumerate(("command -v backstage-cli", "backstage-cli --version",
                                          "backstage-cli --help", "backstage-cli info", "uname -m"), 1):
            self.assertIn(command, self.steps[f"test{number}"]["run"])
        for name in ("install", "version"):
            self.assertNotIn("continue-on-error", self.steps[name])

    def test_install_uses_selected_node_without_sudo_and_publishes_exact_prefix(self):
        result, outputs = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"install_status": "success"}, outputs)
        self.assertEqual(self.env["BACKSTAGE_PREFIX"] + "/node_modules/.bin\n",
                         Path(self.env["GITHUB_PATH"]).read_text())
        arguments = (self.root / "npm-args").read_text().splitlines()
        self.assertEqual(["install", "--prefix", self.env["BACKSTAGE_PREFIX"],
                          "--foreground-scripts", "--loglevel", "verbose", "--logs-dir",
                          str(self.runner_temp / "backstage-npm-logs")], arguments)
        self.assertIn("v24.0.0", result.stdout)
        self.assertIn("11.0.0", result.stdout)
        self.assertNotIn("fixture npm failure details", result.stdout)

    def test_local_manifest_limits_workaround_to_broken_yarn_core_and_satisfies_jsdom_peer(self):
        result, outputs = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        manifest = json.loads((Path(self.env["BACKSTAGE_PREFIX"]) / "package.json").read_text())
        self.assertEqual({"name": "backstage-cli-smoke", "private": True,
                          "dependencies": {"@backstage/cli": "0.36.6", "jsdom": "^27.1.0"},
                          "overrides": {"@yarnpkg/core@4.9.2": {"got": "11.8.6"}}}, manifest)
        self.assertEqual("success", outputs["install_status"])
        for flag in ("--global", "--force", "--legacy-peer-deps", "--ignore-scripts"):
            self.assertNotIn(flag, (self.root / "npm-args").read_text().splitlines())

    def test_npm_failure_prints_debug_log_and_preserves_exit_code(self):
        for code in (1, 37, 127):
            with self.subTest(code=code):
                result, outputs = self.run_step("install", NPM_RC=str(code))
                self.assertEqual(code, result.returncode, result.stderr)
                self.assertEqual({"install_status": "failed"}, outputs)
                self.assertIn("fixture npm failure details", result.stdout)
                self.assertEqual("", Path(self.env["GITHUB_PATH"]).read_text())

    def test_npm_failure_without_debug_log_is_still_the_original_failure(self):
        result, outputs = self.run_step("install", NPM_RC="37", NPM_LOG="0")
        self.assertEqual(37, result.returncode, result.stderr)
        self.assertEqual({"install_status": "failed"}, outputs)

    def test_diagnostic_read_failure_does_not_replace_npm_failure(self):
        self.tool("cat", "exit 19\n")
        result, outputs = self.run_step("install", NPM_RC="37")
        self.assertEqual(37, result.returncode, result.stderr)
        self.assertEqual({"install_status": "failed"}, outputs)

    def test_existing_path_binary_cannot_hide_missing_install(self):
        result, outputs = self.run_step("install", NPM_BINARY="0")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual({"install_status": "failed"}, outputs)
        self.assertEqual("", Path(self.env["GITHUB_PATH"]).read_text())

    def test_version_is_runtime_output_bound_to_installed_package(self):
        result, outputs = self.run_step("version", CLI_STDERR="upstream warning\n")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"version": "0.36.6"}, outputs)
        self.assertIn("upstream warning", result.stderr)
        self.assertEqual("--version\n", (self.root / "cli-calls").read_text())
        self.assertIn('require(process.env.BACKSTAGE_PREFIX + "/node_modules/@backstage/cli/package.json").version',
                      (self.root / "node-calls").read_text())

    def test_version_rejects_failure_malformed_or_mismatched_identity(self):
        for environment in ({"CLI_RC": "37"}, {"CLI_STDOUT": ""}, {"CLI_STDOUT": "unknown"},
                            {"CLI_STDOUT": "error loading 0.36.6"}, {"CLI_STDOUT": "0.36.6\n0.36.6"},
                            {"INSTALLED_VERSION": "0.36.5"}, {"NODE_RC": "1"}):
            with self.subTest(environment=environment):
                result, outputs = self.run_step("version", **environment)
                self.assertNotEqual(0, result.returncode, result.stdout)
                self.assertNotIn("version", outputs)

    def test_real_cli_commands_must_exit_successfully_even_with_matching_text(self):
        for name, text in (("test2", "0.36.6"), ("test3", "Usage: backstage-cli"),
                           ("test4", "OS: Linux arm64")):
            for code in (0, 37):
                with self.subTest(name=name, code=code):
                    result, outputs = self.run_step(name, CLI_STDOUT=text, CLI_RC=str(code))
                    self.assertEqual(code == 0, result.returncode == 0, result.stderr)
                    self.assertEqual("passed" if code == 0 else "failed", outputs["status"])
                    if code == 0:
                        self.assertTrue(outputs["duration"].isdigit())

    def test_successful_cli_exit_with_wrong_output_does_not_pass(self):
        for name in ("test2", "test3", "test4"):
            result, outputs = self.run_step(name, CLI_STDOUT="unexpected")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["status"])

    def test_wrong_host_architecture_is_a_failure(self):
        result, outputs = self.run_step("test5", TEST_ARCH="x86_64")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def test_info_uses_yarn_created_project_and_preserves_setup_failure(self):
        result, outputs = self.run_step("test4", CLI_STDOUT="OS: Linux arm64")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        calls = (self.root / "yarn-calls").read_text().splitlines()
        self.assertEqual(2, len(calls))
        self.assertTrue(calls[0].startswith(str(self.runner_temp / "backstage-info.")))
        self.assertTrue(calls[0].endswith(":init --yes"))
        self.assertTrue(calls[1].endswith(":install --non-interactive"))
        (self.root / "cli-calls").unlink()
        result, outputs = self.run_step("test4", YARN_RC="37")
        self.assertEqual(37, result.returncode, result.stderr)
        self.assertNotEqual("passed", outputs.get("status"))
        self.assertFalse((self.root / "cli-calls").exists())

    def test_summary_cannot_pass_failed_or_missing_core_check(self):
        values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)}
        for number in range(1, 6):
            for status in ("failed", ""):
                with self.subTest(number=number, status=status):
                    result, outputs = self.run_step("summary", values={
                        **values, f"steps.test{number}.outputs.status": status})
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failure", outputs["overall_status"])
                    self.assertEqual("failing", outputs["badge_status"])

    def test_every_workflow_shell_block_parses(self):
        for step in self.job["steps"]:
            if "run" in step:
                result = subprocess.run(["bash", "-n"], input=self.render(step["run"]),
                                        text=True, capture_output=True)
                self.assertEqual(0, result.returncode, step["name"] + result.stderr)


if __name__ == "__main__":
    unittest.main()
