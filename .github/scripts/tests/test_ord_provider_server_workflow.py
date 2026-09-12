"""Execute the ORD workflow probes and summary with controlled package fixtures."""

import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-ord-provider-server.yml"
JOB = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-ord-provider-server"]
STEPS = {step["id"]: step for step in JOB["steps"] if "id" in step}
ACTION = yaml.safe_load((ROOT / ".github/actions/generic-source-regression-check/action.yml").read_text())


def render(script, values):
    def expression(match):
        for term in match[1].split("||"):
            term = term.strip()
            if term.startswith("'") and term.endswith("'"):
                return term[1:-1]
            if values.get(term):
                return str(values[term])
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)


CLI_FIXTURE = r"""
import { appendFileSync } from 'node:fs';
import { createServer } from 'node:http';
const args = process.argv.slice(2);
const fault = process.env.ORD_TEST_FAULT;
appendFileSync(process.env.ORD_TEST_TRACE, `cli ${args.join(' ')}\n`);
if (args[0] === '--version') {
  if (VERSION === '1.2.5' && process.env.DOTENV_CONFIG_QUIET !== 'true') {
    console.log('injected env (0) from .env');
  }
  console.log(fault === 'version' ? '99.0.0' : VERSION);
  process.exit(fault === 'version-exit' ? 7 : 0);
}
if (args[0] === '--help') {
  console.log(fault === 'help-text' ? 'unrelated help' : '--directory --base-url');
  process.exit(fault === 'help-exit' ? 7 : 0);
}
if (fault === 'server-exit') process.exit(9);
const value = flag => args[args.indexOf(flag) + 1];
const baseUrl = value('--base-url');
const serve = (req, res) => {
  if (req.url === '/document.json') {
    res.statusCode = fault === 'document-http' ? 500 : 200;
    res.end(JSON.stringify({openResourceDiscovery: '1.9'}));
  } else if (fault === 'bad-json') {
    res.end('openResourceDiscovery documents baseUrl');
  } else {
    res.end(JSON.stringify({
      baseUrl: fault === 'base-url' ? 'http://other.example' : baseUrl,
      openResourceDiscoveryV1: {documents: fault === 'empty-documents' ? [] : [
        {url: fault === 'external-document' ? 'https://other.example/doc' : '/document.json'}
      ]}
    }));
  }
};
let redirectUrl;
if (fault === 'discovery-redirect' || fault === 'document-redirect') {
  const destination = createServer((req, res) => {
    appendFileSync(process.env.ORD_TEST_TRACE, `off-origin request ${req.url}\n`);
    serve(req, res);
  });
  await new Promise(resolve => destination.listen(0, '127.0.0.1', resolve));
  redirectUrl = `http://127.0.0.1:${destination.address().port}`;
}
const server = createServer((req, res) => {
  if ((fault === 'discovery-redirect' && req.url === '/.well-known/open-resource-discovery') ||
      (fault === 'document-redirect' && req.url === '/document.json')) {
    appendFileSync(process.env.ORD_TEST_TRACE, `redirect ${req.url}\n`);
    res.writeHead(302, {location: `${redirectUrl}${req.url}`});
    res.end();
  } else {
    serve(req, res);
  }
});
server.listen(Number(value('--port')), value('--host'));
"""


class OrdProviderServerWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(shutil.which("node"), "Node is required for the actual workflow probe")
        temporary = tempfile.TemporaryDirectory(prefix="ord-workflow-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.output = self.root / "output"
        self.trace = self.root / "trace"
        self.env = dict(os.environ, **JOB["env"])
        self.env.update(HOME=str(self.root), TMPDIR=str(self.root), RUNNER_TEMP=str(self.root),
                        GITHUB_OUTPUT=str(self.output), ORD_TEST_TRACE=str(self.trace),
                        ORD_TEST_CANDIDATE=str(self.root / "candidate-fixture"),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.values = {f"env.{key}": value for key, value in JOB["env"].items()}
        self.values.update({"steps.install.outputs.install_mode": "github_source",
                            "steps.version.outputs.version": "0.7.3"})
        self.package("baseline-src", "0.7.3", "dist/src/cli.js")
        self.package("candidate-fixture", "1.2.5", "dist/cli.js")
        self.script("npm", r'''
printf 'npm %s\n' "$*" >> "$ORD_TEST_TRACE"
if [ "$*" = "${ORD_NPM_FAIL:-none}" ]; then exit 8; fi
''')
        self.script("git", r'''
printf 'git %s\n' "$*" >> "$ORD_TEST_TRACE"
test "${ORD_CLONE_FAIL:-0}" = 0
test "$*" = 'clone --depth 1 --branch v1.2.5 https://github.com/open-resource-discovery/provider-server.git next-src'
cp -R "$ORD_TEST_CANDIDATE" next-src
''')

    def script(self, name, source):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + source)
        path.chmod(0o755)

    def package(self, directory, version, entrypoint):
        source = self.root / directory
        (source / "example").mkdir(parents=True)
        (source / "package.json").write_text(json.dumps({
            "name": "@open-resource-discovery/provider-server", "version": version,
            "bin": entrypoint, "type": "module",
        }))
        cli = source / entrypoint
        cli.parent.mkdir(parents=True)
        cli.write_text(f"const VERSION = {json.dumps(version)};\n" + CLI_FIXTURE)

    def execute(self, script, extra_env=None):
        self.output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **(extra_env or {})),
                                text=True, capture_output=True, timeout=45)
        outputs = dict(line.split("=", 1) for line in self.output.read_text().splitlines())
        return result, outputs

    def baseline(self, **extra_env):
        return self.execute(render(STEPS["test5"]["run"], self.values), extra_env)

    def candidate(self, **extra_env):
        inputs = {name: spec.get("default", "") for name, spec in ACTION["inputs"].items()}
        inputs.update({name: render(value, self.values) for name, value in STEPS["test6"]["with"].items()})
        values = {f"inputs.{name}": value for name, value in inputs.items()}
        step = ACTION["runs"]["steps"][0]
        env = {name: render(value, values) for name, value in step["env"].items()}
        env.update(extra_env)
        return self.execute(render(step["run"], values), env)

    def summary(self, overrides=None):
        values = dict(self.values)
        for number in range(1, 7):
            values[f"steps.test{number}.outputs.status"] = "passed"
            values[f"steps.test{number}.outputs.duration"] = "1"
            values[f"steps.test{number}.outcome"] = "success"
        values.update(overrides or {})
        return self.execute(render(STEPS["summary"]["run"], values))

    def test_versions_node_and_failure_policy_are_fixed(self):
        self.assertEqual("0.7.3", JOB["env"]["BASELINE_VERSION"])
        self.assertEqual("1.2.5", JOB["env"]["NEXT_VERSION"])
        node = next(step for step in JOB["steps"] if step["name"] == "Set up Node.js")
        self.assertEqual("24", node["with"]["node-version"])
        self.assertEqual("false", STEPS["test6"]["with"]["defer_on_limited_cpu_probe_failure"])
        self.assertIn("Required candidate probe:", STEPS["test6"]["with"]["limited_cpu_description"])
        self.assertNotIn("executed", STEPS["test6"]["with"]["limited_cpu_description"])

    def test_both_declared_cli_layouts_execute_build_version_help_and_http(self):
        for probe, version, entrypoint in ((self.baseline, "0.7.3", "dist/src/cli.js"),
                                           (self.candidate, "1.2.5", "dist/cli.js")):
            with self.subTest(version=version):
                self.trace.write_text("")
                result, outputs = probe()
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("passed", outputs["status"])
                self.assertIn(f"version={version} cli={entrypoint} discovery=200 document=200", result.stdout)
                trace = self.trace.read_text()
                self.assertIn("npm ci\nnpm run build\n", trace)
                self.assertIn("cli --version\ncli --help\ncli -d ", trace)
                port = int(re.search(r"port=(\d+)", result.stdout)[1])
                with socket.socket() as connection:
                    self.assertNotEqual(0, connection.connect_ex(("127.0.0.1", port)))
        self.assertEqual("1.2.5", outputs["next_installed_version"])
        self.assertEqual("limited_cpu_smoke_validated", outputs["decision"])
        self.assertFalse(list(self.root.glob("ord-smoke-*")), "Server temporary state leaked")

    def test_install_and_build_failures_are_not_masked(self):
        for command in ("ci", "run build"):
            for probe in (self.baseline, self.candidate):
                with self.subTest(command=command, probe=probe.__name__):
                    _, outputs = probe(ORD_NPM_FAIL=command)
                    self.assertEqual("failed", outputs["status"])
                    self.assertNotEqual("deferred", outputs.get("next_installed_version"))

    def test_cli_and_http_command_failures_are_not_deferred(self):
        for fault in ("version", "version-exit", "help-text", "help-exit", "server-exit",
                      "bad-json", "base-url", "empty-documents", "external-document", "document-http"):
            for probe in (self.baseline, self.candidate):
                with self.subTest(fault=fault, probe=probe.__name__):
                    result, outputs = probe(ORD_TEST_FAULT=fault)
                    self.assertEqual("failed", outputs["status"], result.stdout + result.stderr)
                    if probe.__name__ == "baseline":
                        self.assertNotEqual(0, result.returncode)
                    else:
                        self.assertEqual("limited_cpu_smoke_failed", outputs["decision"])
                        self.assertIn("failed", outputs["regression_result"])

    def test_missing_candidate_entrypoint_reproduces_failure_and_fails_summary(self):
        (self.root / "candidate-fixture/dist/cli.js").unlink()
        result, outputs = self.candidate()
        self.assertEqual(0, result.returncode, "Shared action reports probe failure through outputs")
        self.assertEqual("failed", outputs["status"])
        self.assertEqual("limited_cpu_probe_failed", outputs["next_installed_version"])
        summary, counts = self.summary({"steps.test6.outputs.status": outputs["status"]})
        self.assertNotEqual(0, summary.returncode)
        self.assertEqual("1", counts["failed"])
        self.assertEqual("0", counts["core_failed"])
        self.assertEqual("failure", counts["overall_status"])

    def assert_redirect_is_rejected(self, fault, endpoint):
        for probe, number in ((self.baseline, 5), (self.candidate, 6)):
            with self.subTest(probe=probe.__name__):
                self.trace.write_text("")
                result, outputs = probe(ORD_TEST_FAULT=fault)
                self.assertEqual("failed", outputs["status"], result.stdout + result.stderr)
                self.assertNotIn("ORD_SMOKE_PASSED", result.stdout)
                self.assertIn(f"redirect {endpoint}\n", self.trace.read_text())
                self.assertNotIn("off-origin request", self.trace.read_text())
                if number == 5:
                    self.assertNotEqual(0, result.returncode)
                else:
                    self.assertEqual("limited_cpu_smoke_failed", outputs["decision"])
                    self.assertEqual("limited_cpu_probe_failed", outputs["next_installed_version"])
                summary, counts = self.summary({f"steps.test{number}.outputs.status": outputs["status"]})
                self.assertNotEqual(0, summary.returncode)
                self.assertEqual("1", counts["failed"])
                self.assertEqual("0", counts["skipped"])
                self.assertEqual("failure", counts["overall_status"])

    def test_discovery_redirect_is_rejected_without_following_or_deferring(self):
        self.assert_redirect_is_rejected("discovery-redirect", "/.well-known/open-resource-discovery")

    def test_document_redirect_is_rejected_without_following_or_deferring(self):
        self.assert_redirect_is_rejected("document-redirect", "/document.json")

    def test_source_identity_and_version_must_match(self):
        package = self.root / "candidate-fixture/package.json"
        original = json.loads(package.read_text())
        for key, value in (("version", "0.7.3"), ("name", "unrelated-package"), ("bin", None)):
            with self.subTest(key=key):
                package.write_text(json.dumps(dict(original, **{key: value})))
                _, outputs = self.candidate()
                self.assertEqual("failed", outputs["status"])

    def test_clone_failure_remains_an_actual_failure(self):
        _, outputs = self.candidate(ORD_CLONE_FAIL="1")
        self.assertEqual("failed", outputs["status"])
        self.assertEqual("next_install_failed", outputs["decision"])

    def test_summary_requires_six_successful_outcomes_and_explicit_passes(self):
        result, outputs = self.summary()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"passed": "6", "failed": "0", "skipped": "0", "duration": "6",
                          "core_failed": "0", "overall_status": "success", "badge_status": "passing"}, outputs)
        for number in range(1, 7):
            for field, value in (("outputs.status", ""), ("outputs.status", "skipped"),
                                 ("outputs.status", "failed"), ("outcome", "failure"),
                                 ("outcome", "cancelled"), ("outcome", "skipped"), ("outcome", "")):
                with self.subTest(test=number, field=field, value=value):
                    result, outputs = self.summary({f"steps.test{number}.{field}": value})
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", outputs["passed"])
                    self.assertEqual("1", outputs["failed"])
                    self.assertEqual("0", outputs["skipped"])
                    self.assertEqual("1" if number < 6 else "0", outputs["core_failed"])
                    self.assertEqual("failure", outputs["overall_status"])


if __name__ == "__main__":
    unittest.main()
