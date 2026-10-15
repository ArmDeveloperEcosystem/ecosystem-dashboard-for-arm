"""Keep Cloudy Pad's historical CLI executable and package accounting honest."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-cloudypad.yml"


class CloudypadWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-cloudypad"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        temporary = tempfile.TemporaryDirectory(prefix="cloudypad-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = {"name": "cloudypad", "version": "0.9.0", "bin": {"cloudypad": "./dist/src/index.js"}}
        (self.root / "dist/src").mkdir(parents=True)
        self.entry = self.root / "dist/src/index.js"
        self.help = "Usage: cloudypad [options] [command]\n  create\n  list\n  configure <name>\n  provision <name>\n"
        self.version = "0.9.0"
        self.exit_code = 0

    def cli_probe(self, **env):
        (self.root / "package.json").write_text(json.dumps(self.package))
        self.entry.write_text(
            "const fs = require('node:fs');\n"
            "fs.appendFileSync(process.env.CALL_LOG, process.argv[2] + '\\n');\n"
            f"if (process.argv[2] === '--help') console.log({json.dumps(self.help)});\n"
            f"else if (process.argv[2] === '--version') console.log({json.dumps(self.version)});\n"
            "else process.exit(99);\n"
            f"process.exit({self.exit_code});\n"
        )
        match = re.search(r"node <<'NODE' > /tmp/cloudypad-help.txt\n(.*?)\nNODE", self.steps["test5"]["run"], re.S)
        self.assertIsNotNone(match)
        # Isolate the workflow's evidence destination; execute its complete JS unchanged.
        script = match[1].replace("'/tmp/cloudypad-version.txt'", "process.env.VERSION_OUTPUT")
        return subprocess.run(
            ["node", "-e", script], cwd=self.root,
            env=dict(os.environ, BASELINE_VERSION="0.9.0", CALL_LOG=str(self.root / "calls"),
                     VERSION_OUTPUT=str(self.root / "version"), **env),
            capture_output=True, text=True, timeout=15,
        )

    def summary(self, overrides):
        values = {f"steps.test{i}.{key}": value for i in range(1, 7)
                  for key, value in (("outputs.status", "passed"), ("outcome", "success"))}
        values.update(overrides)
        def expression(match):
            for part in match[1].split("||"):
                key = part.strip()
                value = key[1:-1] if key.startswith("'") else values.get(key)
                if value:
                    return value
            return ""
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps["summary"]["run"])
        output = self.root / "output"
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(os.environ, GITHUB_OUTPUT=str(output)),
                                capture_output=True, text=True, timeout=10)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_historical_declared_entrypoint_executes_only_help_and_version(self):
        result = self.cli_probe()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["--version", "--help"], (self.root / "calls").read_text().splitlines())
        self.assertEqual("0.9.0\n", (self.root / "version").read_text())
        self.assertIn("cloudypad-cli-preflight-ok version=0.9.0", result.stdout)

    def test_each_historical_command_is_required(self):
        original = self.help
        for command in ("create", "list", "configure", "provision"):
            with self.subTest(command=command):
                self.help = "\n".join(line for line in original.splitlines() if not line.strip().startswith(command))
                self.assertNotEqual(0, self.cli_probe().returncode)

    def test_wrong_package_and_runtime_versions_fail(self):
        self.package["version"] = "0.10.0"
        self.assertNotEqual(0, self.cli_probe().returncode)
        self.package["version"] = "0.9.0"
        self.version = "0.10.0"
        self.assertNotEqual(0, self.cli_probe().returncode)
        self.version = "0.9.0"
        self.package["name"] = "unrelated"
        self.assertNotEqual(0, self.cli_probe().returncode)

    def test_cli_failure_and_missing_executable_fail(self):
        self.exit_code = 17
        self.assertNotEqual(0, self.cli_probe().returncode)
        self.exit_code = 0
        self.package["bin"]["cloudypad"] = "./missing.js"
        self.assertNotEqual(0, self.cli_probe().returncode)
        self.package["bin"]["cloudypad"] = "../outside.js"
        self.assertNotEqual(0, self.cli_probe().returncode)

    def test_unrelated_help_cannot_pass_with_command_words(self):
        self.help = self.help.replace("Usage: cloudypad", "Usage: unrelated")
        self.assertNotEqual(0, self.cli_probe().returncode)

    def test_original_missing_status_is_a_real_core_failure(self):
        result, outputs = self.summary({"steps.test5.outputs.status": "", "steps.test5.outcome": "failure"})
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("5", "1", "0", "1", "failure"), tuple(outputs[k] for k in ("passed", "failed", "skipped", "core_failed", "overall_status")))

    def test_missing_or_failed_outcome_never_becomes_a_pass(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(number=number, outcome=outcome):
                    result, outputs = self.summary({f"steps.test{number}.outcome": outcome})
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("1", outputs["failed"])

    def test_pass_and_explicit_no_newer_release_are_distinct(self):
        result, outputs = self.summary({})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("6", "0", "0"), tuple(outputs[k] for k in ("passed", "failed", "skipped")))
        result, outputs = self.summary({"steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": "no_newer_stable_available"})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1"), tuple(outputs[k] for k in ("passed", "failed", "skipped")))
        result, outputs = self.summary({"steps.test6.outputs.status": "skipped"})
        self.assertNotEqual(0, result.returncode)

    def test_candidate_version_binding_and_baseline_pin_remain(self):
        self.assertEqual("0.9.0", self.job["env"]["BASELINE_VERSION"])
        self.assertIn("p.version !== process.env.LATEST_VERSION", self.steps["test6"]["with"]["limited_cpu_probe"])
        self.assertIn("\"deploy\"", self.steps["test6"]["with"]["limited_cpu_probe"])

    def candidate_probe(self, *, version="0.45.2", name="cloudypad", commands=None):
        commands = commands if commands is not None else ["create", "list", "configure", "deploy"]
        (self.root / "package.json").write_text(json.dumps({"name": name, "version": version}))
        program = self.root / "dist/src/cli/program.js"
        program.parent.mkdir(parents=True, exist_ok=True)
        program.write_text(
            "exports.buildProgram = () => ({\n"
            f"commands: {json.dumps(commands)}.map(name => ({{name: () => name}})),\n"
            "helpInformation: () => 'Usage: cloudypad [options] [command]',\n"
            "parse: () => { throw new Error('CLI execution is forbidden'); },\n"
            "parseAsync: () => { throw new Error('CLI execution is forbidden'); }\n"
            "});\n"
        )
        probe = self.steps["test6"]["with"]["limited_cpu_probe"]
        check = next(line.strip() for line in probe.splitlines() if "p.version !== process.env.LATEST_VERSION" in line)
        registration = next(line.strip() for line in probe.splitlines() if "const program=mod.buildProgram()" in line)
        # Only relocate the output; execute both complete workflow assertions.
        registration = registration.replace("/tmp/cloudypad-next-help.txt", '"$HELP_OUTPUT"')
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", check + "\n" + registration], cwd=self.root,
            env=dict(os.environ, LATEST_VERSION="0.45.2", PROGRAM_JS="dist/src/cli/program.js",
                     HELP_OUTPUT=str(self.root / "candidate-help"), AWS_EC2_METADATA_DISABLED="true"),
            capture_output=True, text=True, timeout=15,
        )

    def test_candidate_registration_passes_without_executing_commands(self):
        result = self.candidate_probe()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("commands=create,list,configure,deploy", (self.root / "candidate-help").read_text())

    def test_candidate_wrong_package_or_version_fails(self):
        for values in ({"version": "0.9.0"}, {"version": "0.45.20"}, {"name": "unrelated"}):
            with self.subTest(values=values):
                self.assertNotEqual(0, self.candidate_probe(**values).returncode)

    def test_candidate_each_registered_command_is_required(self):
        commands = ["create", "list", "configure", "deploy"]
        for missing in commands:
            with self.subTest(missing=missing):
                result = self.candidate_probe(commands=[name for name in commands if name != missing])
                self.assertNotEqual(0, result.returncode)
                self.assertIn("missing Cloudy Pad command: " + missing, result.stderr)


if __name__ == "__main__":
    unittest.main()
