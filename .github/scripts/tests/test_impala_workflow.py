"""Execute Impala discovery, candidate probes and summary with controlled producers."""

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


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-impala.yml"
BASELINE = "4.5.0"
CANDIDATE = "4.5.2"


class ImpalaWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="impala-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-impala"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("date", "rm", "tee", "grep"):
            (self.bin / name).symlink_to(shutil.which(name))
        self.env = {"HOME": str(self.root), "PATH": str(self.bin),
                    "PYTHONDONTWRITEBYTECODE": "1", "FIXTURE_ROOT": str(self.root),
                    "IMPALA_VERSION": BASELINE, "GITHUB_OUTPUT": str(self.root / "output")}
        self.values = {"steps.install.outcome": "success",
                       "steps.install.outputs.image_tag": "fixture-arm64",
                       "steps.install.outputs.work_dir": str(self.root),
                       "steps.version.outcome": "success",
                       "steps.version.outputs.version": BASELINE,
                       "steps.version.outputs.latest": CANDIDATE,
                       "steps.version.outputs.discovery_status": "success",
                       "steps.version.outputs.next_url": self.release(CANDIDATE)["assets"][0]["browser_download_url"],
                       "steps.test6.outputs.current_version": BASELINE,
                       "steps.test6.outputs.latest_version": CANDIDATE,
                       "steps.test6.outputs.next_installed_version": CANDIDATE,
                       "steps.test6.outputs.decision": "next_install_validated"}
        for number in range(1, 7):
            self.values[f"steps.test{number}.outputs.status"] = "passed"
            self.values[f"steps.test{number}.outputs.duration"] = str(number)
            self.values[f"steps.test{number}.outcome"] = "success"
        (self.root / "impala-shell-version.txt").write_text(f"Impala Shell v{BASELINE}-RELEASE (build)\n")
        (self.root / "impalad-version.txt").write_text(f"impalad version {BASELINE}-RELEASE RELEASE (build)\n")
        self.pages = [[self.release(CANDIDATE), self.release(BASELINE)]]
        self.stub("python3", r'''
import io
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

root = Path(os.environ['FIXTURE_ROOT'])
def response(url, timeout):
    assert timeout == 30
    assert url.startswith('https://api.github.com/repos/apache/impala/releases?per_page=100&page=')
    with (root / 'requests').open('a') as log:
        log.write(url + '\n')
    if os.environ.get('API_ERROR'):
        raise urllib.error.HTTPError(url, 403, 'fixture API error', {}, None)
    if os.environ.get('API_BAD_JSON'):
        return io.StringIO('{')
    pages = json.loads((root / 'pages.json').read_text())
    page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['page'][0])
    return io.StringIO(json.dumps(pages[page - 1]))
urllib.request.urlopen = response
sys.argv = sys.argv[1:]
exec(compile(sys.stdin.read(), 'workflow-inline-python', 'exec'))
''')
        self.stub("curl", r'''
import os
from pathlib import Path
import sys
root = Path(os.environ['FIXTURE_ROOT'])
(root / 'download-url').write_text(sys.argv[-1])
sys.exit(int(os.environ.get('CURL_RC', '0')))
''')
        self.stub("dpkg-deb", r'''
import os
from pathlib import Path
import sys
assert sys.argv[1] == '-x'
if os.environ.get('EXTRACT_RC'):
    sys.exit(int(os.environ['EXTRACT_RC']))
root = Path(sys.argv[-1]) / 'opt/impala'
for name in ('sbin/impalad', 'shell/impala-shell'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    path.chmod(0o755)
''')
        self.stub("uname", "import os\nprint(os.environ.get('HOST_ARCH', 'aarch64'))\n")
        self.stub("file", "import os\nprint(os.environ.get('FILE_ARCH', 'ELF 64-bit LSB executable, ARM aarch64'))\n")
        self.stub("docker", r'''
import os
from pathlib import Path
import sys
assert sys.argv[1:5] == ['run', '--rm', '--platform', 'linux/arm64']
assert sys.argv[-1] == '--version'
kind = 'SHELL' if sys.argv[-2].endswith('/impala-shell') else 'SERVER'
with (Path(os.environ['FIXTURE_ROOT']) / 'docker-calls').open('a') as log:
    log.write(kind + '\n')
default = 'Impala Shell v4.5.2-RELEASE (build)' if kind == 'SHELL' else 'impalad version 4.5.2-RELEASE RELEASE (build)'
print(os.environ.get(kind + '_OUTPUT', default))
sys.exit(int(os.environ.get(kind + '_RC', '0')))
''')

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    @staticmethod
    def release(version, **updates):
        name = f"apache-impala-{version}-RELEASE_hive-3.1.3000.7.3.1.0-160-aarch64.ubuntu-20.04.deb"
        result = {"tag_name": version, "draft": False, "prerelease": False,
                  "assets": [{"name": name, "state": "uploaded", "size": 1109295090,
                              "browser_download_url": f"https://github.com/apache/impala/releases/download/{version}/{name}"}]}
        result.update(updates)
        return result

    def render(self, source):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if self.values.get(term):
                    return self.values[term]
            return ""
        source = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)
        return source.replace("/tmp/impala-shell-version.txt", str(self.root / "impala-shell-version.txt")).replace(
            "/tmp/impalad-version.txt", str(self.root / "impalad-version.txt"))

    def run_step(self, name, **env):
        (self.root / "pages.json").write_text(json.dumps(self.pages))
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", self.render(self.steps[name]["run"])],
                                cwd=self.root, env={**self.env, **env}, capture_output=True, text=True, timeout=30)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        return result, outputs

    def publish(self, name, result, outputs):
        prefix = f"steps.{name}."
        self.values = {key: value for key, value in self.values.items() if not key.startswith(prefix)}
        self.values.update({prefix + "outputs." + key: value for key, value in outputs.items()})
        self.values[prefix + "outcome"] = "success" if result.returncode == 0 else "failure"

    def assert_failed(self, result, outputs, decision, code=None):
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        if code is not None:
            self.assertEqual(code, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", outputs["status"])
        self.assertEqual(decision, outputs["decision"])
        self.assertEqual("not_installed", outputs["next_installed_version"])
        self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def assert_summary_failed(self, passed="5", failed="1", skipped="0", core="0"):
        result, summary = self.run_step("summary")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual((passed, failed, skipped, core, "failure", "failing"),
                         tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status", "badge_status")))
        return summary

    def test_pinned_baseline_free_runner_and_secretless_checkout_remain(self):
        self.assertEqual(BASELINE, self.job["env"]["IMPALA_VERSION"])
        self.assertIn("4.5.0-RELEASE_hive-3.1.3-aarch64.ubuntu-20.04.deb", self.job["env"]["IMPALA_RELEASE_URL"])
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertIs(False, self.job["steps"][0]["with"]["persist-credentials"])
        self.assertNotIn("secrets.", WORKFLOW.read_text())
        self.assertNotIn("github.token", WORKFLOW.read_text())
        self.assertTrue(self.steps["version"]["continue-on-error"])
        self.assertIn("steps.summary.outputs.regression_status", self.job["outputs"]["regression_status"])
        self.assertNotIn("'skipped'", self.job["outputs"]["regression_status"])
        self.assertEqual([f"test{i}" for i in range(1, 7)], [key for key in self.steps if re.fullmatch(r"test[1-6]", key)])

    def test_all_shell_steps_parse(self):
        for step in self.job["steps"]:
            if "run" in step:
                result = subprocess.run(["/bin/bash", "-n"], input=self.render(step["run"]), capture_output=True, text=True)
                self.assertEqual(0, result.returncode, step["name"] + result.stderr)

    def test_existing_auditor_sees_version_summary_and_regression_outputs(self):
        root = WORKFLOW.parents[2]
        self.assertTrue(observation_audit._step_emits_output(root, self.steps["version"], "version"))
        for key in ("status", "duration", "current_version", "latest_version", "next_installed_version",
                    "decision", "regression_result", "comparison"):
            self.assertTrue(observation_audit._step_emits_output(root, self.steps["test6"], key), key)
        for key in ("passed", "failed", "skipped", "duration", "core_failed", "overall_status", "badge_status",
                    "regression_status", "regression_decision"):
            self.assertTrue(observation_audit._step_emits_output(root, self.steps["summary"], key), key)
        self.assertEqual({("baseline_failed", "skipped"), ("no_newer_stable_available", "skipped"),
                          ("next_install_validated", "passed"), ("next_lookup_failed", "failed"),
                          ("next_install_failed", "failed")},
                         set(observation_audit._step_literal_pairs(root, self.steps["test6"])))

    def test_real_result_policy_accepts_candidate_pass_and_download_failure(self):
        for env in ({}, {"CURL_RC": "22"}):
            with self.subTest(env=env):
                result, regression = self.run_step("test6", **env)
                self.publish("test6", result, regression)
                result, summary = self.run_step("summary")
                details = [{"name": self.steps[f"test{i}"]["name"], "status": "passed"} for i in range(1, 6)]
                details.append({"name": self.steps["test6"]["name"], **regression})
                counters = {key: int(summary[key]) for key in ("passed", "failed", "skipped", "core_failed")}
                self.assertEqual(summary["overall_status"], result_policy.validate_six_test_result(
                    details=details, **counters, decision=summary["regression_decision"]))

    def test_realistic_changed_hive_suffix_is_discovered_and_probed(self):
        result, version = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(CANDIDATE, version["latest"])
        self.assertEqual(self.release(CANDIDATE)["assets"][0]["browser_download_url"], version["next_url"])
        self.publish("version", result, version)
        result, regression = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(("passed", "next_install_validated", BASELINE, CANDIDATE, CANDIDATE),
                         tuple(regression[key] for key in ("status", "decision", "current_version", "latest_version", "next_installed_version")))
        self.assertEqual(version["next_url"], (self.root / "download-url").read_text())
        self.assertEqual(["SHELL", "SERVER"], (self.root / "docker-calls").read_text().splitlines())
        self.publish("test6", result, regression)
        result, summary = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("6", "0", "0", "success", "passing"),
                         tuple(summary[key] for key in ("passed", "failed", "skipped", "overall_status", "badge_status")))

    def test_nearest_newer_does_not_require_baseline_in_page_or_lexical_order(self):
        self.pages = [[self.release("4.10.0"), self.release(CANDIDATE),
                       self.release("4.5.1", draft=True), self.release("4.5.1", prerelease=True),
                       self.release("4.5.1-rc1"), self.release("4.4.9")]]
        result, outputs = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(CANDIDATE, outputs["latest"])

    def test_pagination_selects_nearest_newer_from_later_page(self):
        self.pages = [[self.release(f"3.0.{i}") for i in range(99)] + [self.release("4.10.0")],
                      [self.release(BASELINE), self.release(CANDIDATE)]]
        result, outputs = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(CANDIDATE, outputs["latest"])
        self.assertEqual(2, len((self.root / "requests").read_text().splitlines()))

    def test_complete_discovery_is_required_for_no_newer_skip(self):
        self.pages = [[self.release(BASELINE), self.release("4.4.1")]]
        result, outputs = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.publish("version", result, outputs)
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("no_newer_stable_available", outputs["decision"])
        self.assertEqual("skipped", outputs["status"])
        self.publish("test6", result, outputs)
        result, summary = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1"), tuple(summary[key] for key in ("passed", "failed", "skipped")))
        self.assertFalse((self.root / "download-url").exists())

    def test_api_errors_malformed_empty_and_incomplete_discovery_fail_closed(self):
        cases = [(self.pages, {"API_ERROR": "1"}), (self.pages, {"API_BAD_JSON": "1"}),
                 ([{"message": "API rate limit"}], {}), ([[]], {}),
                 ([[self.release("4.4.1")]], {}), ([[{"tag_name": CANDIDATE}]], {}),
                 ([[self.release(CANDIDATE, draft="false")]], {}),
                 ([[self.release(CANDIDATE, prerelease=None)]], {}),
                 ([[self.release(CANDIDATE)] * 100], {})]
        for pages, env in cases:
            with self.subTest(pages=pages[:1], env=env):
                self.pages = pages
                result, outputs = self.run_step("version", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("discovery_status", outputs)
                self.publish("version", result, outputs)
                result, outputs = self.run_step("test6")
                self.assert_failed(result, outputs, "next_lookup_failed")
                self.publish("test6", result, outputs)
                self.assert_summary_failed()
        self.assertFalse((self.root / "download-url").exists())

    def test_missing_ambiguous_wrong_platform_and_untrusted_assets_fail(self):
        original = self.release(CANDIDATE)["assets"][0]
        cases = [[], [original, original]]
        for key, value in (("name", original["name"].replace("aarch64", "x86_64")),
                           ("name", original["name"].replace("20.04", "22.04")),
                           ("name", original["name"] + ".asc"), ("state", "new"), ("size", 0),
                           ("browser_download_url", "https://example.invalid/impala.deb")):
            cases.append([{**original, key: value}])
        for assets in cases:
            with self.subTest(assets=assets):
                self.pages = [[self.release(CANDIDATE, assets=assets), self.release(BASELINE), self.release("4.6.0")]]
                result, outputs = self.run_step("version")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(CANDIDATE, outputs["latest"])
                self.assertNotIn("discovery_status", outputs)
                self.assertNotIn("next_url", outputs)
                self.publish("version", result, outputs)
                result, outputs = self.run_step("test6")
                self.assert_failed(result, outputs, "next_lookup_failed")
                self.publish("test6", result, outputs)
                self.assert_summary_failed()

    def test_invalid_baseline_cannot_fall_back_to_pin(self):
        for name in ("impala-shell-version.txt", "impalad-version.txt"):
            path = self.root / name
            original = path.read_text()
            for text in ("", original.replace(BASELINE, "4.5.20"), original + original):
                with self.subTest(name=name, text=text):
                    path.write_text(text)
                    result, outputs = self.run_step("version")
                    self.assertNotEqual(0, result.returncode)
                    self.assertNotIn("version", outputs)
            path.write_text(original)

    def test_producer_failures_preserve_exit_codes_even_with_correct_banners(self):
        for env, code in (({"CURL_RC": "22"}, 22), ({"EXTRACT_RC": "2"}, 2),
                          ({"SHELL_RC": "17"}, 17), ({"SERVER_RC": "23"}, 23)):
            with self.subTest(env=env):
                result, outputs = self.run_step("test6", **env)
                self.assert_failed(result, outputs, "next_install_failed", code)
                self.assertIn(f"(exit {code})", result.stdout)
                self.publish("test6", result, outputs)
                self.assert_summary_failed()

    def test_candidate_requires_both_exact_versions_and_native_arm64(self):
        for env in ({"SHELL_OUTPUT": ""}, {"SERVER_OUTPUT": ""},
                    {"SHELL_OUTPUT": "Impala Shell v4.5.20-RELEASE (build)"},
                    {"SERVER_OUTPUT": "impalad version 4.5.0-RELEASE RELEASE (build)"},
                    {"SERVER_OUTPUT": "error mentions Impala 4.5.2"},
                    {"FILE_ARCH": "ELF 64-bit LSB executable, x86-64"}, {"HOST_ARCH": "x86_64"}):
            with self.subTest(env=env):
                self.assert_failed(*self.run_step("test6", **env), "next_install_failed")

    def test_missing_and_contradictory_test6_outcomes_never_become_skip_or_pass(self):
        for status, decision, outcome in (("", "", "failure"), ("", "", "success"),
                ("passed", "next_install_validated", "failure"), ("passed", "next_install_validated", "cancelled"),
                ("passed", "next_install_validated", "skipped"), ("passed", "next_install_validated", ""),
                ("skipped", "no_newer_stable_available", "failure"), ("skipped", "no_newer_stable_available", "success"),
                ("skipped", "baseline_failed", "success"), ("skipped", "not_configured", "success"),
                ("passed", "no_newer_stable_available", "success"), ("nonsense", "next_install_failed", "success")):
            with self.subTest(status=status, decision=decision, outcome=outcome):
                self.values.update({"steps.test6.outputs.status": status, "steps.test6.outputs.decision": decision,
                                    "steps.test6.outcome": outcome})
                summary = self.assert_summary_failed()
                self.assertEqual("failed", summary["regression_status"])
                self.assertEqual("next_install_failed", summary["regression_decision"])

    def test_summary_requires_current_selected_and_installed_version_proof(self):
        for field in ("current_version", "latest_version", "next_installed_version"):
            key = "steps.test6.outputs." + field
            original = self.values[key]
            for value in ("", "unknown", "4.4.1"):
                with self.subTest(field=field, value=value):
                    self.values[key] = value
                    self.assert_summary_failed()
            self.values[key] = original

    def test_failed_discovery_outcome_overrides_stale_success_outputs(self):
        for key, value in (("steps.version.outcome", "failure"), ("steps.version.outputs.discovery_status", ""),
                           ("steps.version.outputs.version", ""), ("steps.install.outcome", "failure")):
            original = self.values[key]
            self.values[key] = value
            self.assert_summary_failed()
            self.values[key] = original

    def test_core_outcomes_and_baseline_skip_are_honest(self):
        for number in range(1, 6):
            key = f"steps.test{number}.outcome"
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(number=number, outcome=outcome):
                    self.values[key] = outcome
                    result, outputs = self.run_step("test6")
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("baseline_failed", outputs["decision"])
                    self.publish("test6", result, outputs)
                    self.assert_summary_failed(passed="4", failed="1", skipped="1", core="1")
            self.values[key] = "success"

    def test_missing_results_and_bad_durations_fail_closed(self):
        for step in ("test2", "test6"):
            for duration in ("bad", "-1", "1.5", "1000000"):
                self.values[f"steps.{step}.outputs.duration"] = duration
                result, outputs = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failure", outputs["overall_status"])
            self.values[f"steps.{step}.outputs.duration"] = "08"
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("29", outputs["duration"])
        self.values.clear()
        self.assert_summary_failed(passed="0", failed="6", skipped="0", core="5")


if __name__ == "__main__":
    unittest.main()
