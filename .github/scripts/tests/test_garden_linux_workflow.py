"""Execute Garden Linux metadata, source probes, and summary with controlled inputs."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-garden-linux.yml"
ROOT = WORKFLOW.parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import package_result_policy as policy  # noqa: E402


BASH = os.environ.get("GARDEN_LINUX_WORKFLOW_BASH", shutil.which("bash"))
BASH_MAJOR = int(subprocess.check_output(
    [BASH, "-c", 'printf "%s" "${BASH_VERSINFO[0]}"'], text=True))
BASELINE = "934.0"
CANDIDATE = "2150.12.0"
TOKEN = "garden-linux-fixture-token"


class GardenLinuxWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="garden-linux-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-garden-linux"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.tmp = self.root / "runner temp"
        self.tmp.mkdir()
        for name in ("date", "rm", "mktemp", "mv", "jq", "grep", "make", "find",
                     "head", "mkdir", "ln", "cat"):
            (self.bin / name).symlink_to(shutil.which(name))
        (self.bin / "bash").symlink_to(BASH)
        self.env = {**self.job["env"], "HOME": str(self.root), "PATH": str(self.bin),
                    "RUNNER_TEMP": str(self.tmp), "FIXTURE_ROOT": str(self.root),
                    "GITHUB_OUTPUT": str(self.root / "output"),
                    "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
                    "CANDIDATE_TAG": CANDIDATE, "PYTHONDONTWRITEBYTECODE": "1"}
        if "DEVELOPER_DIR" in os.environ:
            self.env["DEVELOPER_DIR"] = os.environ["DEVELOPER_DIR"]
        self.values = {"github.token": TOKEN, "steps.install.outputs.install_mode": "github_source",
                       "steps.metadata.outputs.package_slug": "garden-linux",
                       "steps.metadata.outputs.dashboard_link": "/linux/opensource_packages/garden-linux",
                       "steps.metadata.outputs.timestamp": "2026-10-15T00:00:00Z",
                       "steps.version.outputs.version": BASELINE,
                       "github.run_id": "123", "github.run_attempt": "1", "github.job": "test-garden-linux",
                       "steps.test6.outputs.decision": "limited_cpu_smoke_validated",
                       "steps.test6.outputs.current_version": BASELINE,
                       "steps.test6.outputs.latest_version": CANDIDATE,
                       "steps.test6.outputs.next_installed_version": CANDIDATE,
                       "steps.test6.outputs.regression_result": "Arm preflight proof passed on Arm64",
                       "steps.test6.outputs.comparison": self.steps["test6"]["with"]["limited_cpu_description"]}
        for number in range(1, 7):
            self.values[f"steps.test{number}.outputs.status"] = "passed"
            self.values[f"steps.test{number}.outputs.duration"] = str(number)
            self.values[f"steps.test{number}.outcome"] = "success"
        self.pages = [[self.release(CANDIDATE)], [self.release(BASELINE)]]
        self.cache = self.tmp / "garden-linux-releases.json"
        self.cache.write_text(json.dumps([release for page in self.pages for release in page]))
        self.stub("gh", r'''
import os
from pathlib import Path
import sys
root = Path(os.environ['FIXTURE_ROOT'])
(root / 'gh-called').touch()
assert os.environ['GH_TOKEN'] == 'garden-linux-fixture-token'
assert sys.argv[1:] == ['api', '--hostname', 'github.com', '--method', 'GET',
    'https://api.github.com/repos/gardenlinux/gardenlinux/releases?per_page=100', '--paginate', '--slurp']
sys.stdout.write((root / 'pages.json').read_text())
sys.exit(int(os.environ.get('API_RC', '0')))
''')
        self.stub("timeout", r'''
import os
import sys
assert sys.argv[1:4] == ['--kill-after=10s', '120s', 'gh']
if os.environ.get('TIMEOUT_RC'):
    sys.exit(int(os.environ['TIMEOUT_RC']))
os.execvp(sys.argv[3], sys.argv[3:])
''')
        self.stub("python3", r'''
import json
import os
from pathlib import Path
import sys
with (Path(os.environ['FIXTURE_ROOT']) / 'source-calls').open('a') as log:
    log.write(json.dumps({'args': sys.argv[1:], 'tokens':
        {key: os.environ[key] for key in ('GH_TOKEN', 'GITHUB_TOKEN') if key in os.environ}}) + '\n')
assert 'GH_TOKEN' not in os.environ and 'GITHUB_TOKEN' not in os.environ
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
''')
        for name in ("curl", "git"):
            self.stub(name, "raise AssertionError('Unexpected network access from source probe')\n")
        for source in ("baseline-src", "next-src"):
            directory = self.root / source
            for name in ("bin", "features", "platforms", "build", "images"):
                (directory / name).mkdir(parents=True)
            (directory / "README.md").write_text("Garden Linux image build fixture\n")
            (directory / "Makefile").write_text(
                'CHECK := $(shell python3 -c "pass")\nall:\n\t@echo Garden Linux dry-run\n')
            (directory / "bin/helper.py").write_text("answer = 42\n")
            (directory / "bin/gl-flavors-parse").write_text("#!/bin/bash\ntrue\n")

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    @staticmethod
    def release(tag, names=None):
        if names is None:
            names = [f"gardenlinux-{tag}-arm64.raw", "gardenlinux-amd64.tar.gz", "SHA256SUMS"]
        return {"tag_name": tag, "assets": [{"name": name} for name in names]}

    def render(self, source):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if self.values.get(term):
                    return self.values[term]
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source).replace(
            "/tmp/garden-linux-", str(self.root / "garden-linux-"))

    def run_step(self, name, payload=None, **env):
        (self.root / "pages.json").write_text(json.dumps(self.pages) if payload is None else payload)
        step = self.steps[name]
        script = step["with"]["limited_cpu_probe"] if name == "test6" else step["run"]
        step_env = {key: self.render(value) for key, value in step.get("env", {}).items()}
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run([BASH, "-euo", "pipefail", "-c", self.render(script)],
                                cwd=self.root, env={**self.env, **step_env, **env},
                                capture_output=True, text=True, timeout=30)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        self.assertNotIn(TOKEN, result.stdout + result.stderr + output.read_text())
        return result, outputs

    def publish(self, name, result, outputs):
        prefix = f"steps.{name}."
        self.values = {key: value for key, value in self.values.items() if not key.startswith(prefix)}
        self.values.update({prefix + "outputs." + key: value for key, value in outputs.items()})
        self.values[prefix + "outcome"] = "success" if result.returncode == 0 else "failure"

    def assert_summary(self, passed=6, failed=0, skipped=0, core=0):
        result, outputs = self.run_step("summary")
        self.assertEqual(failed == 0, result.returncode == 0, result.stdout + result.stderr)
        self.assertEqual((passed, failed, skipped, core), tuple(
            int(outputs[key]) for key in ("passed", "failed", "skipped", "core_failed")))
        self.assertEqual(6, passed + failed + skipped)
        self.assertEqual("failure" if failed else "success", outputs["overall_status"])
        self.assertEqual("failing" if failed else "passing", outputs["badge_status"])
        self.assertRegex(outputs["duration"], r"^[0-9]+$")
        return outputs

    def assert_baseline_failed(self):
        result, outputs = self.run_step("test5")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", outputs["status"])
        self.assertRegex(outputs["duration"], r"^[0-9]+$")
        self.publish("test5", result, outputs)
        self.assert_summary(passed=5, failed=1, core=1)

    def candidate_gate(self, step):
        condition = step.get("if", "").strip()
        if condition.startswith("${{") and condition.endswith("}}"):
            condition = condition[3:-2].strip()
        clauses = [clause.strip() for clause in condition.split("&&")]
        expected = {f"steps.test{number}.{field} == '{value}'": (f"steps.test{number}.{field}", value)
                    for number in range(1, 6)
                    for field, value in (("outputs.status", "passed"), ("outcome", "success"))}
        self.assertCountEqual(expected, clauses, step["name"])
        return all(self.values.get(key, "") == value for key, value in expected.values())

    def skip_candidate(self, outcome="skipped"):
        self.values = {key: value for key, value in self.values.items() if not key.startswith("steps.test6.")}
        self.values["steps.test6.outcome"] = outcome

    def collect_summary(self, summary, api_conclusions=None):
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        self.values.update({f"steps.summary.outputs.{key}": value for key, value in summary.items()})
        outputs = {key: self.render(value) for key, value in self.job["outputs"].items()}
        if api_conclusions is None:
            api_conclusions = [self.values.get(f"steps.test{number}.outcome") or "skipped"
                               for number in range(1, 7)]
        self.assertEqual(6, len(api_conclusions))
        step_numbers = {step.get("id"): number for number, step in enumerate(self.job["steps"], 1)}
        api_steps = [{"name": self.steps[f"test{number}"]["name"],
                      "number": step_numbers[f"test{number}"], "conclusion": conclusion}
                     for number, conclusion in enumerate(api_conclusions, 1)]
        api_steps.append({"name": self.steps["summary"]["name"], "number": step_numbers["summary"],
                          "conclusion": summary["overall_status"]})
        job = {"id": 456, "name": "test-garden-linux / test-garden-linux",
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "conclusion": summary["overall_status"], "steps": api_steps}
        with tempfile.TemporaryDirectory(prefix="collector-", dir=self.root) as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(ROOT / ".github/scripts")
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GH_TOKEN": "", "GITHUB_TOKEN": "",
                   "NEEDS_JSON": json.dumps({"test-garden-linux": {
                       "result": summary["overall_status"], "outputs": outputs}}),
                   "RUN_JOBS_JSON": json.dumps({"jobs": [job]}),
                   "BATCH_NUMBER": "1", "BATCH_TITLE": "Batch 1",
                   "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
                   "GITHUB_REPOSITORY": "example/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                   "GITHUB_OUTPUT": str(root / "outputs"), "GITHUB_STEP_SUMMARY": str(root / "summary")}
            result = subprocess.run([sys.executable, "-B", "-c", source], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=30)
            artifact = root / "test-results/garden-linux-test-results/garden-linux.json"
            return result, json.loads(artifact.read_text()) if artifact.exists() else None

    def test_token_is_confined_to_trusted_fetch_before_source_execution(self):
        steps = self.job["steps"]
        self.assertLess(steps.index(self.steps["releases"]), steps.index(self.steps["install"]))
        self.assertNotIn("continue-on-error", self.steps["releases"])
        self.assertEqual({"GH_TOKEN": "${{ github.token }}"}, self.steps["releases"]["env"])
        self.assertNotRegex(json.dumps(self.job["env"]), r"GH_TOKEN|GITHUB_TOKEN|github.token")
        for step in steps:
            if step.get("id") != "releases":
                self.assertNotRegex(json.dumps(step), r"GH_TOKEN|GITHUB_TOKEN|github.token")
        self.assertFalse(steps[0]["with"]["persist-credentials"])
        self.assertEqual(BASELINE, self.job["env"]["BASELINE_VERSION"])
        self.assertEqual("./.github/actions/generic-source-regression-check", self.steps["test6"]["uses"])
        self.assertEqual("false", self.steps["test6"]["with"]["defer_on_limited_cpu_probe_failure"])
        self.assertNotIn("env", self.steps["test6"])
        self.assertNotIn("next_version_override", self.steps["test6"]["with"])
        self.assertNotIn("candidate_tag_override", self.steps["test6"]["with"])
        for script in (self.steps["test5"]["run"], self.steps["test6"]["with"]["limited_cpu_probe"]):
            self.assertNotRegex(script, r"curl|gh api|api.github.com|\beval\b")

    def test_fetch_validates_and_flattens_all_pages_at_fixed_public_endpoint(self):
        result, _ = self.run_step("releases", GH_HOST="attacker.invalid", GITHUB_REPO="attacker/repo")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([self.release(CANDIDATE), self.release(BASELINE)], json.loads(self.cache.read_text()))
        self.assertFalse(list(self.tmp.glob("garden-linux-release-pages.*")))
        self.assertFalse(self.cache.with_suffix(".json.tmp").exists())

    def test_fetch_rejects_nonpublic_server_or_api_before_gh(self):
        for env in ({"GITHUB_SERVER_URL": "https://enterprise.invalid"},
                    {"GITHUB_API_URL": "https://attacker.invalid"}):
            with self.subTest(env=env):
                result, _ = self.run_step("releases", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse((self.root / "gh-called").exists())
                self.assertFalse(self.cache.exists())

    def test_fetch_errors_timeouts_and_malformed_payloads_leave_no_stale_cache(self):
        cases = [("{", {}), ("", {}), ("[]", {}), ('{"message":"Forbidden"}', {}),
                 ('[[{"tag_name":"934.0","assets":null}]]', {}),
                 ('[[{"tag_name":934,"assets":[]}]]', {}),
                 ('[[{"tag_name":"934.0","assets":[{"name":5}]}]]', {}),
                 ('[[{"tag_name":"934.0","assets":[{}]}]]', {}),
                 (json.dumps([[self.release(BASELINE)], {}]), {}),
                 (json.dumps([[self.release(BASELINE), self.release(BASELINE)]]), {}),
                 (json.dumps(self.pages) + "\n[]", {}),
                 (json.dumps(self.pages), {"API_RC": "1"}),
                 (json.dumps(self.pages), {"TIMEOUT_RC": "124"})]
        for payload, env in cases:
            with self.subTest(payload=payload, env=env):
                self.cache.write_text("stale successful metadata")
                result, _ = self.run_step("releases", payload=payload, **env)
                self.assertNotEqual(0, result.returncode, result.stderr)
                self.assertFalse(self.cache.exists())
                self.assertFalse(list(self.tmp.glob("garden-linux-release-pages.*")))
                self.assertFalse(self.cache.with_suffix(".json.tmp").exists())

    def test_payload_is_data_not_shell_or_output_commands(self):
        injected = '$(touch injected);`touch injected`\nstatus=passed'
        self.pages = [[self.release(BASELINE, [injected + "-arm64.raw", "amd64.tar"])]]
        result, _ = self.run_step("releases")
        self.assertEqual(0, result.returncode, result.stderr)
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertFalse((self.root / "injected").exists())

    def test_baseline_accepts_any_arm_asset_not_only_last_asset(self):
        for architecture in ("arm64", "AARCH64"):
            with self.subTest(architecture=architecture):
                self.pages = [[self.release(BASELINE, [f"image-{architecture}.raw", "amd64.tar", "SHA256SUMS"])]]
                result, _ = self.run_step("releases")
                self.assertEqual(0, result.returncode, result.stderr)
                result, outputs = self.run_step("test5")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("passed", outputs["status"])
                self.assertIn("OS boot, systemd, kernel modules, and cloud-init remain out of scope", outputs["note"])
        calls = [json.loads(line) for line in (self.root / "source-calls").read_text().splitlines()]
        self.assertTrue(any(call["args"][:2] == ["-m", "compileall"] for call in calls))
        self.assertTrue(any(call["args"] == ["-c", "pass"] for call in calls))
        self.assertTrue(all(not call["tokens"] for call in calls))

    def test_baseline_missing_exact_tag_empty_or_non_arm_metadata_fails(self):
        for releases in ([], [self.release(BASELINE + ".0")], [self.release("v" + BASELINE)],
                         [self.release(CANDIDATE)], [self.release(BASELINE, [])],
                         [self.release(BASELINE, ["amd64.tar", "image.raw", "rootfs.qcow"])],
                         [self.release(BASELINE), self.release(BASELINE)]):
            with self.subTest(releases=releases):
                self.cache.write_text(json.dumps(releases))
                self.assert_baseline_failed()

    @unittest.skipIf(BASH_MAJOR < 4, "Candidate requires Bash 4+; set GARDEN_LINUX_WORKFLOW_BASH")
    def test_valid_fetch_with_missing_tags_or_non_arm_assets_cannot_pass_probes(self):
        for pages in ([[]], [[self.release(BASELINE + ".0"), self.release("v" + CANDIDATE)]],
                      [[self.release(BASELINE, ["amd64.tar"])], [self.release(CANDIDATE, ["image.raw"])]]):
            with self.subTest(pages=pages):
                self.pages = pages
                result, _ = self.run_step("releases")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assert_baseline_failed()
                result, _ = self.run_step("test6")
                self.assertNotEqual(0, result.returncode, result.stderr)

    def test_baseline_absent_or_corrupt_cache_fails(self):
        for payload in (None, "{", "null", '{"message":"Forbidden"}'):
            with self.subTest(payload=payload):
                if payload is None:
                    self.cache.unlink()
                else:
                    self.cache.write_text(payload)
                self.assert_baseline_failed()

    def test_baseline_source_evidence_makefile_and_external_fallback_fail_closed(self):
        readme = self.root / "baseline-src/README.md"
        readme.write_text("Unrelated source\n")
        makefile = self.root / "baseline-src/Makefile"
        makefile.write_text("all:\n\t@true\n")
        self.assert_baseline_failed()
        readme.write_text("Garden Linux\n")
        makefile.write_text("all: missing-required-target\n")
        self.assert_baseline_failed()
        makefile.unlink()
        self.assert_baseline_failed()
        self.values["steps.install.outputs.install_mode"] = "external_artifact"
        self.assert_baseline_failed()

    @unittest.skipIf(BASH_MAJOR < 4, "Candidate requires Bash 4+; set GARDEN_LINUX_WORKFLOW_BASH")
    def test_candidate_uses_exact_tag_and_no_network_or_token(self):
        result, _ = self.run_step("releases")
        self.assertEqual(0, result.returncode, result.stderr)
        result, _ = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        calls = [json.loads(line) for line in (self.root / "source-calls").read_text().splitlines()]
        self.assertTrue(any(call["args"][:2] == ["-m", "py_compile"] for call in calls))
        self.assertTrue(all(not call["tokens"] for call in calls))
        for releases in ([self.release(BASELINE)], [self.release("v" + CANDIDATE)],
                         [self.release(CANDIDATE + ".0")], [self.release(CANDIDATE, [])],
                         [self.release(CANDIDATE, ["amd64.tar", "image.raw", "rootfs.qcow"])],
                         [self.release(CANDIDATE), self.release(CANDIDATE)]):
            with self.subTest(releases=releases):
                self.cache.write_text(json.dumps(releases))
                result, _ = self.run_step("test6")
                self.assertNotEqual(0, result.returncode, result.stderr)
        for payload in (None, "{"):
            if payload is None:
                self.cache.unlink()
            else:
                self.cache.write_text(payload)
            result, _ = self.run_step("test6")
            self.assertNotEqual(0, result.returncode, result.stderr)

    @unittest.skipIf(BASH_MAJOR < 4, "Candidate requires Bash 4+; set GARDEN_LINUX_WORKFLOW_BASH")
    def test_candidate_retains_source_shell_and_python_preflight(self):
        for name in ("features", "bin", "Makefile"):
            path = self.root / "next-src" / name
            backup = path.with_name(path.name + ".held")
            path.rename(backup)
            result, _ = self.run_step("test6")
            backup.rename(path)
            self.assertNotEqual(0, result.returncode, result.stderr)
        helper = self.root / "next-src/bin/helper.py"
        helper.write_text("def invalid syntax\n")
        result, _ = self.run_step("test6")
        self.assertNotEqual(0, result.returncode, result.stderr)
        helper.write_text("answer = 42\n")
        (self.root / "next-src/bin/gl-flavors-parse").write_text("if then\n")
        result, _ = self.run_step("test6")
        self.assertNotEqual(0, result.returncode, result.stderr)

    def test_summary_success_and_explicit_allowed_skips(self):
        outputs = self.assert_summary()
        self.assertEqual("21", outputs["duration"])
        self.assertEqual("passed", outputs["regression_status"])
        for decision in ("no_newer_stable_available", "runtime_validation_not_automated", "metadata_review_required"):
            with self.subTest(decision=decision):
                self.values.update({"steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": decision})
                outputs = self.assert_summary(passed=5, skipped=1)
                self.assertEqual("skipped", outputs["regression_status"])
                self.assertEqual(decision, outputs["regression_decision"])

    def test_every_core_requires_both_passed_status_and_success_outcome(self):
        for number in range(1, 6):
            for status, outcome in (("", "success"), ("failed", "success"), ("skipped", "success"),
                                    ("passed", "failure"), ("passed", "cancelled"),
                                    ("passed", "skipped"), ("passed", ""), ("", "failure")):
                with self.subTest(number=number, status=status, outcome=outcome):
                    self.values[f"steps.test{number}.outputs.status"] = status
                    self.values[f"steps.test{number}.outcome"] = outcome
                    self.assert_summary(passed=5, failed=1, core=1)
            self.values[f"steps.test{number}.outputs.status"] = "passed"
            self.values[f"steps.test{number}.outcome"] = "success"

    def test_allowed_regression_skip_does_not_hide_core_failure(self):
        self.values.update({"steps.test5.outputs.status": "", "steps.test5.outcome": "failure",
                            "steps.test6.outputs.status": "skipped",
                            "steps.test6.outputs.decision": "no_newer_stable_available"})
        outputs = self.assert_summary(passed=4, failed=1, skipped=1, core=1)
        self.assertEqual("skipped", outputs["regression_status"])

    def test_test6_missing_contradictory_and_failed_results_never_pass_or_skip(self):
        for status, decision, outcome in (("", "", "success"), ("", "", "failure"),
                ("passed", "limited_cpu_smoke_validated", "failure"),
                ("passed", "limited_cpu_smoke_validated", "skipped"),
                ("passed", "limited_cpu_smoke_validated", ""), ("passed", "", "success"),
                ("skipped", "no_newer_stable_available", "failure"), ("skipped", "not_configured", "success"),
                ("skipped", "limited_cpu_smoke_failed", "success"),
                ("failed", "limited_cpu_smoke_failed", "success"), ("failed", "next_install_failed", "success")):
            with self.subTest(status=status, decision=decision, outcome=outcome):
                self.values.update({"steps.test6.outputs.status": status, "steps.test6.outputs.decision": decision,
                                    "steps.test6.outcome": outcome})
                outputs = self.assert_summary(passed=5, failed=1)
                self.assertEqual("failed", outputs["regression_status"])
                self.assertIn(outputs["regression_decision"], ("limited_cpu_smoke_failed", "next_install_failed"))

    def test_reported_incident_maps_missing_test5_and_failed_candidate_honestly(self):
        self.values.update({"steps.test5.outputs.status": "", "steps.test5.outcome": "failure",
                            "steps.test6.outputs.status": "failed", "steps.test6.outcome": "success",
                            "steps.test6.outputs.decision": "limited_cpu_smoke_failed"})
        outputs = self.assert_summary(passed=4, failed=2, core=1)
        for key, value in outputs.items():
            self.values[f"steps.summary.outputs.{key}"] = value
        emitted = {key: self.render(value) for key, value in self.job["outputs"].items()}
        self.assertEqual(("failure", "failing", "1", "2", "0", "failed", "limited_cpu_smoke_failed"),
                         tuple(emitted[key] for key in ("run_status", "badge_status", "core_failed", "tests_failed",
                                                        "tests_skipped", "regression_status", "regression_decision")))

    def test_python_setup_and_candidate_require_all_five_core_statuses_and_outcomes(self):
        setup = next(step for step in self.job["steps"] if step.get("uses", "").startswith("actions/setup-python@"))
        for step in (setup, self.steps["test6"]):
            self.assertTrue(self.candidate_gate(step))
            for number in range(1, 6):
                for field, bad_values in (("outputs.status", ("", "failed", "skipped")),
                                          ("outcome", ("", "failure", "cancelled", "skipped"))):
                    key = f"steps.test{number}.{field}"
                    original = self.values[key]
                    for value in bad_values:
                        with self.subTest(step=step["name"], number=number, field=field, value=value):
                            self.values[key] = value
                            self.assertFalse(self.candidate_gate(step))
                    self.values[key] = original

    def test_real_baseline_failure_skips_candidate_and_publishes_failed_result(self):
        (self.root / "baseline-src/Makefile").write_text("all: missing-required-target\n")
        result, outputs = self.run_step("test5")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.publish("test5", result, outputs)
        setup = next(step for step in self.job["steps"] if step.get("uses", "").startswith("actions/setup-python@"))
        self.assertFalse(self.candidate_gate(setup))
        self.assertFalse(self.candidate_gate(self.steps["test6"]))
        self.skip_candidate()
        summary = self.assert_summary(passed=4, failed=1, skipped=1, core=1)
        self.assertEqual(("skipped", "baseline_failed"),
                         (summary["regression_status"], summary["regression_decision"]))
        collected, payload = self.collect_summary(summary)
        self.assertEqual(0, collected.returncode, collected.stderr)
        self.assertEqual("2.0", payload["schema_version"])
        self.assertEqual({"name": "Garden Linux", "version": BASELINE}, payload["package"])
        self.assertEqual(["passed"] * 4 + ["failed", "skipped"],
                         [detail["status"] for detail in payload["tests"]["details"]])
        self.assertEqual((4, 1, 1), tuple(payload["tests"][key] for key in ("passed", "failed", "skipped")))
        self.assertEqual(1, payload["metadata"]["core_failed"])
        self.assertEqual("baseline_failed", payload["tests"]["details"][5]["decision"])
        self.assertEqual("failure", policy.validate_publishable_result(payload))

        collected, payload = self.collect_summary(summary, ["success"] * 4 + ["failure", "failure"])
        self.assertNotEqual(0, collected.returncode)
        self.assertIn("emitted skipped count contradicts test details", collected.stderr)
        self.assertIsNone(payload)

    def test_each_core_failure_with_unrun_candidate_has_publishable_baseline_skip(self):
        for number in range(1, 6):
            for candidate_outcome in ("skipped", ""):
                with self.subTest(number=number, candidate_outcome=candidate_outcome):
                    self.values[f"steps.test{number}.outputs.status"] = "failed"
                    self.values[f"steps.test{number}.outcome"] = "failure"
                    self.skip_candidate(candidate_outcome)
                    summary = self.assert_summary(passed=4, failed=1, skipped=1, core=1)
                    self.assertEqual(("skipped", "baseline_failed"),
                                     (summary["regression_status"], summary["regression_decision"]))
                    collected, payload = self.collect_summary(summary)
                    self.assertEqual(0, collected.returncode, collected.stderr)
                    self.assertEqual("failed", payload["tests"]["details"][number - 1]["status"])
                    self.assertEqual("skipped", payload["tests"]["details"][5]["status"])
                    self.assertEqual("failure", policy.validate_publishable_result(payload))
                    self.values[f"steps.test{number}.outputs.status"] = "passed"
                    self.values[f"steps.test{number}.outcome"] = "success"

    def test_unrun_candidate_without_core_failure_cannot_become_baseline_skip(self):
        for outcome in ("skipped", ""):
            with self.subTest(outcome=outcome):
                self.skip_candidate(outcome)
                summary = self.assert_summary(passed=5, failed=1)
                self.assertEqual(("failed", "next_install_failed"),
                                 (summary["regression_status"], summary["regression_decision"]))
                collected, payload = self.collect_summary(summary)
                self.assertEqual(0, collected.returncode, collected.stderr)
                self.assertEqual("failure", policy.validate_publishable_result(payload))

    def test_actually_run_candidate_with_core_failure_is_not_rewritten_or_publishable(self):
        self.values.update({"steps.test5.outputs.status": "failed", "steps.test5.outcome": "failure"})
        for status, decision, outcome in (("passed", "limited_cpu_smoke_validated", "success"),
                                         ("failed", "limited_cpu_smoke_failed", "success"),
                                         ("failed", "next_install_failed", "failure"),
                                         ("failed", "next_install_failed", "cancelled"),
                                         ("skipped", "no_newer_stable_available", "success")):
            with self.subTest(status=status, decision=decision, outcome=outcome):
                self.values.update({"steps.test6.outputs.status": status, "steps.test6.outputs.decision": decision,
                                    "steps.test6.outcome": outcome})
                summary = self.assert_summary(passed=4 + int(status == "passed"),
                                              failed=1 + int(status == "failed"),
                                              skipped=int(status == "skipped"), core=1)
                self.assertEqual((status, decision), (summary["regression_status"], summary["regression_decision"]))
                collected, payload = self.collect_summary(summary)
                self.assertEqual(0, collected.returncode, collected.stderr)
                self.assertEqual((status, decision), (payload["tests"]["details"][5]["status"],
                                                     payload["tests"]["details"][5]["decision"]))
                with self.assertRaisesRegex(ValueError, "baseline failures require an approved baseline decision"):
                    policy.validate_publishable_result(payload)

    def test_candidate_only_failure_remains_publishable(self):
        self.values.update({"steps.test6.outputs.status": "failed", "steps.test6.outcome": "success",
                            "steps.test6.outputs.decision": "limited_cpu_smoke_failed"})
        summary = self.assert_summary(passed=5, failed=1)
        collected, payload = self.collect_summary(summary)
        self.assertEqual(0, collected.returncode, collected.stderr)
        self.assertEqual(["passed"] * 5 + ["failed"],
                         [detail["status"] for detail in payload["tests"]["details"]])
        self.assertEqual("limited_cpu_smoke_failed", payload["tests"]["details"][5]["decision"])
        self.assertEqual("failure", policy.validate_publishable_result(payload))

    def test_all_missing_results_and_output_defaults_are_fail_closed(self):
        self.values = {}
        summary = self.assert_summary(passed=0, failed=5, skipped=1, core=5)
        self.assertEqual(("skipped", "baseline_failed"),
                         (summary["regression_status"], summary["regression_decision"]))
        for key, expected in (("core_failed", "5"), ("tests_failed", "6"), ("regression_status", "failed"),
                              ("run_status", "failure"), ("tests_skipped", "0")):
            self.assertEqual(expected, self.render(self.job["outputs"][key]))

    def test_summary_treats_untrusted_values_as_data_and_validates_durations(self):
        for number in range(1, 7):
            for duration in ("-1", "invalid", "9999999", 'x[$(touch injected)]'):
                with self.subTest(number=number, duration=duration):
                    self.values[f"steps.test{number}.outputs.duration"] = duration
                    self.assert_summary(passed=5, failed=1, core=int(number < 6))
                    self.assertFalse((self.root / "injected").exists())
            self.values[f"steps.test{number}.outputs.duration"] = str(number)
        self.values["steps.test5.outputs.status"] = '$(touch injected)'
        self.assert_summary(passed=5, failed=1, core=1)
        self.assertFalse((self.root / "injected").exists())


if __name__ == "__main__":
    unittest.main()
