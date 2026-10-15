"""Focused checks for the package workflow's actual Bash steps."""

import os
from pathlib import Path
import re
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-playwright.yml"


class PlaywrightWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="playwright-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-playwright"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.env = dict(os.environ, **self.job["env"], GITHUB_OUTPUT=str(self.root / "output"),
                        RUNNER_TEMP=str(self.root), TMPDIR=str(self.root),
                        FIXTURE_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        (self.root / "baseline-src").mkdir()
        self.values = {"steps.install.outputs.install_mode": "github_source",
                       "steps.install.outputs.install_status": "success"}

    def stub(self, name, content):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + content)
        path.chmod(0o755)

    def run_script(self, script, values=None, **env):
        values = {**self.values, **(values or {})}

        def expression(match):
            for term in match[1].split("||"):
                key = term.strip()
                value = (key[1:-1] if key.startswith("'") else
                         self.env.get(key[4:]) if key.startswith("env.") else values.get(key))
                if value:
                    return str(value)
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=20)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if line)
        return result, outputs

    def run_step(self, name, values=None, **env):
        return self.run_script(self.steps[name]["run"], values, **env)

    def passing(self):
        return {key: value for i in range(1, 7) for key, value in (
            (f"steps.test{i}.outputs.status", "passed"), (f"steps.test{i}.outcome", "success"))}

    def runtime_fixture(self):
        self.env["FIXTURE_NODE"] = shutil.which("node") or self.skipTest("Node is required")
        (self.root / "baseline-src/package.json").write_text('{"name":"playwright-internal"}')
        modules = self.root / "fixture-modules"
        self.env["FIXTURE_MODULES"] = str(modules)
        for name in ("@playwright/test", "playwright-core", ".bin"):
            (modules / name).mkdir(parents=True)
        for name in ("@playwright/test", "playwright-core"):
            (modules / name / "package.json").write_text(json.dumps({"name": name, "version": "1.17.0"}))
        (modules / "playwright-core/browsers.json").write_text(json.dumps({
            "browsers": [{"name": "chromium", "revision": "939194"}]}))
        (modules / "playwright-core/index.js").write_text('''
const path = require('path');
exports.chromium = { executablePath() {
  return path.join(process.env.PLAYWRIGHT_BROWSERS_PATH,
    `chromium-${process.env.FIXTURE_REVISION || '939194'}`, 'chrome-linux', 'chrome');
}};
''')
        # Fixture-only API: executes the embedded test callback and exact assertions, not a browser.
        (modules / "@playwright/test/index.js").write_text('''
const assert = require('assert');
exports.test = (name, callback) => {
  let html = '';
  const page = {
    async setContent(value) { html = value; },
    locator(selector) { assert.strictEqual(selector, '#arm'); return selector; }
  };
  exports.expect = selector => ({async toHaveText(expected) {
    assert.strictEqual(selector, '#arm');
    assert.strictEqual(html, '<main id="arm">Playwright Arm smoke</main>');
    assert.strictEqual(process.env.FIXTURE_DOM || 'Playwright Arm smoke', expected);
  }});
  Promise.resolve().then(() => callback({page, browser: {version: () => 'fixture-browser'}}))
    .then(() => console.log('fixture DOM assertion completed'))
    .catch(error => { console.error(error); process.exitCode = 1; });
};
exports.expect = (...args) => exports.expect(...args);
''')
        (self.root / "node-fixture.js").write_text('''
Object.defineProperty(process, 'arch', {value: process.env.FIXTURE_ARCH || 'arm64'});
''')
        self.env["FIXTURE_NODE_BOOTSTRAP"] = str(self.root / "node-fixture.js")
        self.stub("node", 'exec "$FIXTURE_NODE" --require "$FIXTURE_NODE_BOOTSTRAP" "$@"\n')
        self.stub("sudo", 'echo dependency-diagnostic; exit "${FIXTURE_APT_RC:-0}"\n')
        self.stub("file", 'echo "$1: ELF 64-bit LSB pie executable, ${FIXTURE_ELF_ARCH:-ARM aarch64}"\n')
        self.stub("timeout", 'test "$1" = --kill-after=10s\ntest "$2" = 600s -o "$2" = 90s\nshift 2\nexec "$@"\n')
        self.stub("npm", r'''
test "$*" = "install --save-exact --no-audit --no-fund @playwright/test@1.17.0"
test "$PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD" = 1
echo npm-diagnostic
if [ "${FIXTURE_NPM_RC:-0}" != 0 ]; then exit "$FIXTURE_NPM_RC"; fi
cp -R "$FIXTURE_MODULES" node_modules
''')
        cli = modules / ".bin/playwright"
        cli.write_text('''#!/bin/bash
set -euo pipefail
case "$1" in
  --version) echo "Version ${FIXTURE_CLI_VERSION:-1.17.0}" ;;
  install)
    test "$*" = 'install chromium'
    echo browser-install-diagnostic
    if [ "${FIXTURE_INSTALL_RC:-0}" != 0 ]; then exit "$FIXTURE_INSTALL_RC"; fi
    mkdir -p "$PLAYWRIGHT_BROWSERS_PATH/chromium-939194/chrome-linux"
    touch "$PLAYWRIGHT_BROWSERS_PATH/chromium-939194/chrome-linux/chrome"
    ;;
  test)
    test "$*" = 'test smoke.spec.js --project=chromium'
    echo browser-test-diagnostic
    if [ "${FIXTURE_TEST_RC:-0}" != 0 ]; then exit "$FIXTURE_TEST_RC"; fi
    node -e "const c=require('./playwright.config.js'), a=require('assert'); a.strictEqual(c.workers,1); a.strictEqual(c.timeout,30000); a.strictEqual(c.projects.length,1); a.strictEqual(c.projects[0].name,'chromium'); a.strictEqual(c.projects[0].use.browserName,'chromium'); a.strictEqual(c.projects[0].use.headless,true); a.deepStrictEqual(c.projects[0].use.launchOptions.args,['--js-flags=--jitless']); require('./smoke.spec.js')"
    ;;
  *) exit 99 ;;
esac
''')
        cli.chmod(0o755)

    def test_runtime_executes_embedded_named_project_and_dom_assertion(self):
        self.runtime_fixture()
        result, output = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output["status"])
        self.assertEqual("1.17.0", output["installed_version"])
        self.assertTrue(output["duration"].isdigit())
        self.assertIn("fixture DOM assertion completed", result.stdout)

    def test_runtime_rejects_wrong_version_name_architecture_revision_and_dom(self):
        self.runtime_fixture()
        for env in ({"FIXTURE_ARCH": "x64"}, {"FIXTURE_ELF_ARCH": "x86-64"},
                    {"FIXTURE_REVISION": "999999"}, {"FIXTURE_CLI_VERSION": "1.18.0"},
                    {"FIXTURE_DOM": "wrong content"}, {"FIXTURE_TEST_RC": "134"},
                    {"FIXTURE_NPM_RC": "1"}, {"FIXTURE_APT_RC": "100"},
                    {"FIXTURE_INSTALL_RC": "1"}):
            with self.subTest(env=env):
                result, output = self.run_step("test5", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])
                self.assertTrue(output["duration"].isdigit())
                self.assertNotIn("installed_version", output)
        for name in ("@playwright/test", "playwright-core"):
            path = Path(self.env["FIXTURE_MODULES"]) / name / "package.json"
            original = path.read_text()
            for key, value in (("name", "unrelated"), ("version", "1.18.0")):
                with self.subTest(name=name, key=key):
                    path.write_text(json.dumps({**json.loads(original), key: value}))
                    result, output = self.run_step("test5")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", output["status"])
            path.write_text(original)

    def test_hidden_bootstrap_and_browser_errors_are_reported(self):
        self.runtime_fixture()
        for variable, marker in (("FIXTURE_NPM_RC", "npm-diagnostic"),
                                 ("FIXTURE_INSTALL_RC", "browser-install-diagnostic"),
                                 ("FIXTURE_TEST_RC", "browser-test-diagnostic")):
            result, output = self.run_step("test5", **{variable: "1"})
            self.assertEqual("failed", output["status"])
            self.assertIn("Diagnostic:", result.stdout)
            self.assertIn(marker, result.stdout)

    def test_runtime_rejects_external_source_substitution(self):
        result, output = self.run_step("test5", {"steps.install.outputs.install_mode": "external_artifact"})
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])

    def test_candidate_source_probe_does_not_claim_an_installed_browser(self):
        self.assertEqual("not_installed", self.job["outputs"]["regression_next_installed_version"])
        summary = next(s for s in self.job["steps"] if s.get("uses", "").endswith("write-package-job-summary"))
        self.assertEqual("not_installed", summary["with"]["regression_next_installed_version"])

    def test_summary_requires_both_passed_output_and_successful_outcome(self):
        result, output = self.run_step("summary", self.passing())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", output["passed"])
        for i in range(1, 7):
            for field, value in (("outputs.status", ""), ("outputs.status", "skipped"),
                                 ("outputs.status", "failed"), ("outputs.status", "invalid"),
                                 ("outcome", ""), ("outcome", "failure"),
                                 ("outcome", "cancelled"), ("outcome", "skipped")):
                with self.subTest(i=i, field=field, value=value):
                    values = {**self.passing(), f"steps.test{i}.{field}": value,
                              f"steps.test{i}.conclusion": "success"}
                    result, output = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", output["passed"])
                    self.assertEqual("1", output["failed"])
                    self.assertEqual(str(int(i < 6)), output["core_failed"])
                    self.assertEqual("failure", output["overall_status"])
                    self.assertEqual("failing" if i < 6 else "passing", output["badge_status"])
        result, output = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("6", output["failed"])
        self.assertEqual("5", output["core_failed"])
        self.assertEqual("0", output["skipped"])

    def test_only_successful_no_newer_candidate_skip_is_allowed(self):
        for decision in ("", "no_newer_stable_available", "not_configured",
                         "runtime_validation_not_automated", "not_applicable_package_manager"):
            for outcome in ("success", "", "failure", "skipped", "cancelled"):
                with self.subTest(decision=decision, outcome=outcome):
                    values = {**self.passing(), "steps.test6.outputs.status": "skipped",
                              "steps.test6.outputs.decision": decision, "steps.test6.outcome": outcome}
                    result, output = self.run_step("summary", values)
                    accepted = decision == "no_newer_stable_available" and outcome == "success"
                    self.assertEqual(accepted, result.returncode == 0)
                    self.assertEqual(str(int(accepted)), output["skipped"])
                    self.assertEqual(str(int(not accepted)), output["failed"])
        values = {"steps.test6.outputs.status": "skipped", "steps.test6.outcome": "success",
                  "steps.test6.outputs.decision": "no_newer_stable_available"}
        result, output = self.run_step("summary", values)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("5", output["core_failed"])
        self.assertEqual("5", output["failed"])


if __name__ == "__main__":
    unittest.main()
