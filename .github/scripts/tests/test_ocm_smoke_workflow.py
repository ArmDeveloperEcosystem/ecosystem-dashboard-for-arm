"""Run OCM workflow blocks offline; no upstream resolution or real Go build."""

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


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-ocm.yml"


class OCMSmokeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)["jobs"]["test-ocm"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        temporary = tempfile.TemporaryDirectory(prefix="ocm workflow ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.bash = shutil.which("bash")
        self.assertIsNotNone(self.bash)
        for name in ("grep", "head"):
            executable = shutil.which(name)
            self.assertIsNotNone(executable)
            (self.bin / name).symlink_to(executable)
        (self.bin / "python3").symlink_to(sys.executable)
        self.output = self.root / "outputs"
        self.env = {**os.environ, **self.job["env"], "PATH": str(self.bin),
                    "GITHUB_OUTPUT": str(self.output), "RUNNER_TEMP": str(self.root),
                    "FIXTURE_ROOT": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}
        self.tool("date", """from pathlib import Path
import os
p = Path(os.environ['FIXTURE_ROOT']) / 'clock'
print(107 if p.exists() else 100)
p.touch()
""")
        self.tool("uname", "import os; print(os.environ.get('ARCH', 'aarch64'))\n")
        self.tool("go", """import os, sys, time
from pathlib import Path
root = Path(os.environ['FIXTURE_ROOT'])
with (root / 'calls').open('a') as f:
    f.write('go ' + ' '.join(sys.argv[1:]) + '\\n')
assert sys.argv[1:] in (['list', './...'], ['list', './cmd/...']), sys.argv
prefix = 'GO' if sys.argv[-1] == './...' else 'CMD'
if os.environ.get('GO_STALL') == '1':
    time.sleep(60)
if os.environ.get('FAKE_PASSED') == '1':
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as f:
        f.write('status=passed\\n')
print(os.environ.get(prefix + '_OUTPUT', 'ocm.software/ocm/api'), end='')
rc = int(os.environ.get(prefix + '_RC', '0'))
if rc:
    print('smithy-go@v1.12.1: proxy.golang.org INTERNAL_ERROR', file=sys.stderr)
sys.exit(rc)
""")
        # Portable deadline fixture: run and reap the controlled tool, without GNU timeout.
        self.tool("timeout", """import os, subprocess, sys
from pathlib import Path
assert sys.argv[1] == '--kill-after=10s', sys.argv
assert sys.argv[2] == ('900s' if sys.argv[-1] == './...' else '180s'), sys.argv
with (Path(os.environ['FIXTURE_ROOT']) / 'calls').open('a') as f:
    f.write('timeout ' + ' '.join(sys.argv[1:3]) + '\\n')
try:
    result = subprocess.run(sys.argv[3:], timeout=0.2 if os.environ.get('GO_STALL') else 5)
except subprocess.TimeoutExpired:
    print('fixture command timed out', file=sys.stderr)
    sys.exit(124)
sys.exit(result.returncode)
""")
        for source in ("baseline-src", "next-src"):
            directory = self.root / source
            (directory / "api").mkdir(parents=True)
            (directory / "go.mod").write_text("module ocm.software/ocm\n")
            (directory / "README.md").write_text("Open Component Model\n")
        page = self.root / "content/linux/opensource_packages/ocm.md"
        page.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "content/linux/opensource_packages/ocm.md", page)
        self.values = {"steps.install.outcome": "success", "steps.install.outputs.install_mode": "github_source",
                       "env.BASELINE_VERSION": "0.1.0",
                       "steps.install.outputs.install_status": "success", "steps.version.outcome": "success",
                       "steps.version.outputs.version": "0.1.0", "steps.candidate.outcome": "success",
                       "steps.candidate.outputs.status": "passed",
                       "steps.candidate.outputs.decision": "limited_cpu_smoke_validated",
                       "steps.candidate.outputs.current_version": "0.1.0",
                       "steps.candidate.outputs.latest_version": "0.2.0",
                       "steps.candidate.outputs.next_installed_version": "0.2.0",
                       "steps.candidate.outputs.duration": "7",
                       "steps.test6.outputs.decision": "limited_cpu_smoke_validated"}
        for n in range(1, 7):
            self.values.update({f"steps.test{n}.outcome": "success", f"steps.test{n}.outputs.status": "passed",
                                f"steps.test{n}.outputs.duration": "7"})
        result, fields = self.step("expectations")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.values.update({f"steps.expectations.outputs.{k}": v for k, v in fields.items()})

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    def render(self, source, values=None):
        context = {**self.values, **(values or {})}

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if context.get(term):
                    return str(context[term])
            return ""

        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)

    def shell(self, script, values=None, **env):
        self.output.write_text("")
        (self.root / "clock").unlink(missing_ok=True)
        result = subprocess.run([self.bash, "-euo", "pipefail", "-c", self.render(script, values)],
                                cwd=self.root, env={**self.env, **env}, capture_output=True, text=True, timeout=10)
        fields = dict(line.split("=", 1) for line in self.output.read_text().splitlines())
        return result, fields

    def step(self, name, values=None, **env):
        step = self.steps[name]
        environment = {k: self.render(v, values) for k, v in step.get("env", {}).items()}
        return self.shell(step["run"], values, **{**environment, **env})

    def candidate_enabled(self, values):
        # Evaluate this workflow's actual simple conjunction, including success() semantics.
        for term in self.steps["candidate"]["if"].split("&&"):
            term = term.strip()
            if term == "success()":
                if any(v != "success" for k, v in values.items() if k.endswith(".outcome")
                       and k != "steps.candidate.outcome"):
                    return False
            else:
                match = re.fullmatch(r"(steps\.\w+\.outputs\.\w+) == ('[^']+'|env\.\w+)", term)
                self.assertIsNotNone(match, term)
                expected = match[2][1:-1] if match[2].startswith("'") else values.get(match[2])
                if values.get(match[1]) != expected:
                    return False
        return True

    def run_checks(self, failed_core=None, **env):
        values = dict(self.values)
        conclusions = []
        for n in range(1, 6):
            environment = env if n == 5 else {}
            overrides = {}
            if n == failed_core:
                overrides = {1: {"steps.expectations.outputs.source_markers": "missing|absent"},
                             2: {"steps.expectations.outputs.content_page": "missing"},
                             3: {"steps.expectations.outputs.identity_target": "missing"}}.get(n, {})
                if n == 4:
                    environment = {"ARCH": "x86_64"}
                elif n == 5:
                    environment = {**env, "GO_RC": "1"}
            result, fields = self.step(f"test{n}", {**values, **overrides}, **environment)
            outcome = "success" if result.returncode == 0 else "failure"
            values[f"steps.test{n}.outcome"] = outcome
            values.update({f"steps.test{n}.outputs.{k}": v for k, v in fields.items()})
            conclusions.append(outcome)
        if self.candidate_enabled(values):
            # Candidate resolution remains shared; execute OCM's unchanged source probe here.
            result, _ = self.shell(self.steps["candidate"]["with"]["limited_cpu_probe"])
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            values["steps.candidate.outcome"] = "skipped"
            for key in list(values):
                if key.startswith("steps.candidate.outputs."):
                    values[key] = ""
        result, fields = self.step("test6", values)
        outcome = "success" if result.returncode == 0 else "failure"
        values["steps.test6.outcome"] = outcome
        values.update({f"steps.test6.outputs.{k}": v for k, v in fields.items()})
        conclusions.append(outcome)
        result, summary = self.step("summary", values)
        self.assertEqual(result.returncode == 0, summary["overall_status"] == "success")
        return summary, values, conclusions

    def collect(self, summary, values, conclusions):
        context = {**values, **{f"steps.summary.outputs.{k}": v for k, v in summary.items()},
                   "steps.metadata.outputs.package_slug": "ocm", "github.job": "test-ocm"}
        outputs = {k: self.render(v, context) for k, v in self.job["outputs"].items()}
        job = {"id": 456, "name": "test-ocm / test-ocm", "conclusion": summary["overall_status"],
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "steps": [{"name": self.steps[f"test{n}"]["name"], "number": n, "conclusion": state}
                         for n, state in enumerate(conclusions, 1)]}
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(ROOT / ".github/scripts")
            env = {**self.env, "GH_TOKEN": "", "BATCH_NUMBER": "20", "BATCH_TITLE": "Batch 20",
                   "NEEDS_JSON": json.dumps({"test-ocm": {"result": job["conclusion"], "outputs": outputs}}),
                   "RUN_JOBS_JSON": json.dumps({"jobs": [job]}),
                   "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
                   "GITHUB_REPOSITORY": "example/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                   "GITHUB_OUTPUT": str(root / "outputs"), "GITHUB_STEP_SUMMARY": str(root / "summary")}
            result = subprocess.run([sys.executable, "-B", "-c", source], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=20)
            path = root / "test-results/ocm-test-results/ocm.json"
            return result, json.loads(path.read_text()) if path.exists() else None

    def test_scope_and_unmasked_core_scheduling(self):
        self.assertEqual(self.job["env"]["BASELINE_VERSION"], "0.1.0")
        self.assertEqual(self.job["runs-on"], "ubuntu-24.04-arm")
        for n in range(1, 7):
            self.assertNotIn("continue-on-error", self.steps[f"test{n}"])
            self.assertEqual(self.steps[f"test{n}"]["if"], "always()")
        candidate = self.steps["candidate"]
        self.assertEqual(candidate["uses"], "./.github/actions/generic-source-regression-check")
        self.assertNotIn("next_version_override", candidate["with"])
        self.assertNotIn("candidate_tag_override", candidate["with"])
        self.assertIn("This does not build or run the OCM CLI.", candidate["with"]["limited_cpu_description"])
        self.assertNotRegex(WORKFLOW.read_text(), r"GOSUMDB|GONOSUMDB|GOPROXY|insecure|continue-on-error")

    def test_source_graph_positive_and_collector_agree(self):
        summary, values, conclusions = self.run_checks()
        self.assertEqual((summary["passed"], summary["failed"], summary["skipped"]), ("6", "0", "0"))
        self.assertEqual(summary["duration"], "42")
        self.assertIn("no CLI package was available", values["steps.test5.outputs.note"])
        self.assertIn("go list ./...", (self.root / "calls").read_text())
        result, payload = self.collect(summary, values, conclusions)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["tests"]["passed"], 6)

    def test_go_failure_and_timeout_emit_terminal_failure(self):
        for env, code in (({"GO_RC": "1", "GO_OUTPUT": ""}, 1), ({"GO_STALL": "1"}, 124),
                          ({"GO_RC": "23", "FAKE_PASSED": "1"}, 23), ({"GO_OUTPUT": ""}, 1)):
            with self.subTest(env=env):
                result, fields = self.step("test5", **env)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(fields["status"], "failed")
                self.assertEqual(fields["duration"], "7")
                if "GO_RC" in env:
                    self.assertIn("proxy.golang.org INTERNAL_ERROR", result.stderr)
                if "GO_STALL" in env:
                    self.assertIn("timed out", result.stderr)

    def test_optional_command_discovery_does_not_mask_go_failure(self):
        (self.root / "baseline-src/cmd").mkdir()
        result, fields = self.step("test5", CMD_OUTPUT="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["status"], "passed")
        result, fields = self.step("test5", CMD_RC="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(fields["status"], "failed")
        self.assertEqual(fields["duration"], "7")

    def test_each_core_unexpected_failure_has_status_and_duration(self):
        cases = {1: {"steps.install.outputs.install_status": "failed"},
                 2: {"steps.expectations.outputs.content_page": "missing"},
                 3: {"steps.expectations.outputs.identity_target": "missing"},
                 4: {"steps.expectations.outputs.content_page": "missing"},
                 5: {"steps.install.outputs.install_mode": "external_artifact"}}
        for n, values in cases.items():
            with self.subTest(test=n):
                result, fields = self.step(f"test{n}", values)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(fields["status"], "failed")
                self.assertEqual(fields["duration"], "7")

    def test_baseline_failure_skips_candidate_and_collects_actual_api_failure(self):
        for env in ({"GO_RC": "1"}, {"GO_STALL": "1"}, {"FAKE_PASSED": "1", "GO_RC": "1"}):
            with self.subTest(env=env):
                summary, values, conclusions = self.run_checks(**env)
                self.assertEqual(values["steps.candidate.outcome"], "skipped")
                self.assertEqual(values["steps.test6.outputs.decision"], "baseline_failed")
                self.assertEqual(values["steps.test6.outputs.status"], "skipped")
                self.assertEqual(values["steps.test6.outputs.next_installed_version"], "not_installed")
                self.assertEqual(conclusions, ["success"] * 4 + ["failure", "success"])
                self.assertEqual((summary["passed"], summary["failed"], summary["skipped"], summary["core_failed"]),
                                 ("4", "1", "1", "1"))
                result, payload = self.collect(summary, values, conclusions)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(payload["run"]["status"], "failure")
                self.assertEqual(payload["tests"]["failed"], 1)
                self.assertEqual(payload["tests"]["skipped"], 1)
                result, _ = self.collect(summary, values, ["success"] * 6)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("emitted failure counts contradict", result.stderr)

    def test_candidate_gate_requires_every_baseline_status_and_raw_outcome(self):
        self.assertTrue(self.candidate_enabled(self.values))
        for n in range(1, 6):
            for field, value in (("outcome", "failure"), ("outputs.status", ""), ("outputs.status", "failed")):
                with self.subTest(test=n, field=field):
                    self.assertFalse(self.candidate_enabled({**self.values, f"steps.test{n}.{field}": value}))
        for key, value in (("steps.install.outcome", "failure"), ("steps.install.outputs.install_status", ""),
                           ("steps.version.outcome", "failure"), ("steps.version.outputs.version", "")):
            with self.subTest(key=key):
                self.assertFalse(self.candidate_enabled({**self.values, key: value}))

    def test_each_raw_core_failure_matches_collector_without_collapsing_passes(self):
        for n in range(1, 6):
            with self.subTest(test=n):
                summary, values, conclusions = self.run_checks(failed_core=n)
                self.assertEqual(conclusions[n - 1], "failure")
                self.assertEqual(summary["overall_status"], "failure")
                self.assertEqual((summary["passed"], summary["failed"], summary["skipped"]), ("4", "1", "1"))
                result, payload = self.collect(summary, values, conclusions)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(payload["tests"]["passed"], 4)
                self.assertEqual(payload["tests"]["details"][n - 1]["status"], "failed")

    def test_summary_fails_closed_for_missing_or_conflicting_evidence(self):
        for n in range(1, 7):
            for field, value in (("outcome", "failure"), ("outcome", "timed_out"), ("outcome", ""),
                                 ("outputs.status", ""), ("outputs.status", "failed")):
                with self.subTest(test=n, field=field, value=value):
                    result, summary = self.step("summary", {f"steps.test{n}.{field}": value})
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(summary["failed"], "1")
                    self.assertEqual(summary[f"test{n}_status"], "failed")
                    self.assertEqual(summary["overall_status"], "failure")

    def test_empty_workflow_evidence_never_passes(self):
        result, summary = self.step("summary", {key: "" for key in self.values if key.startswith("steps.")})
        self.assertEqual(result.returncode, 1)
        self.assertEqual((summary["passed"], summary["failed"], summary["core_failed"]), ("0", "6", "5"))
        self.assertEqual(summary["duration"], "0")

    def test_original_raw_go_failure_and_passed_test6_are_counted_honestly(self):
        values = {**self.values, "steps.test5.outcome": "failure", "steps.test5.outputs.status": "",
                  "steps.test5.outputs.duration": ""}
        result, summary = self.step("summary", values)
        self.assertEqual(result.returncode, 1)
        self.assertEqual((summary["passed"], summary["failed"], summary["skipped"]), ("5", "1", "0"))
        result, payload = self.collect(summary, values, ["success"] * 4 + ["failure", "success"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["tests"]["details"][5]["status"], "passed")

    def test_candidate_wrapper_exposes_failure_even_with_passed_output(self):
        for values in ({"steps.candidate.outcome": "failure"}, {"steps.candidate.outputs.status": ""},
                       {"steps.candidate.outputs.status": "failed",
                        "steps.candidate.outputs.decision": "limited_cpu_smoke_failed"}):
            with self.subTest(values=values):
                result, fields = self.step("test6", values)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(fields["status"], "failed")
                self.assertEqual(fields["duration"], "7")
                if values.get("steps.candidate.outputs.status") == "failed":
                    self.assertEqual(fields["decision"], "limited_cpu_smoke_failed")

    def test_candidate_failure_is_raw_nonzero_and_collector_agrees(self):
        values = {**self.values, "steps.candidate.outputs.status": "failed",
                  "steps.candidate.outputs.decision": "limited_cpu_smoke_failed",
                  "steps.candidate.outputs.next_installed_version": "limited_cpu_probe_failed"}
        result, fields = self.step("test6", values)
        self.assertEqual(result.returncode, 1)
        values.update({f"steps.test6.outputs.{key}": value for key, value in fields.items()})
        values["steps.test6.outcome"] = "failure"
        result, summary = self.step("summary", values)
        self.assertEqual(result.returncode, 1)
        self.assertEqual((summary["passed"], summary["failed"], summary["core_failed"]), ("5", "1", "0"))
        result, payload = self.collect(summary, values, ["success"] * 5 + ["failure"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["tests"]["failed"], 1)

    def test_skipped_core_or_failed_prerequisite_cannot_pass(self):
        for values in ({"steps.test2.outcome": "skipped", "steps.test2.outputs.status": ""},
                       {"steps.install.outcome": "failure"}, {"steps.version.outcome": "failure"},
                       {"steps.version.outputs.version": ""}):
            with self.subTest(values=values):
                result, summary = self.step("summary", values)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(summary["overall_status"], "failure")

    def test_existing_semantic_skips_remain_accepted_but_unknown_skip_fails(self):
        for decision in ("no_newer_stable_available", "runtime_validation_not_automated", "metadata_review_required",
                         "not_configured", "baseline_failed"):
            with self.subTest(decision=decision):
                result, summary = self.step("summary", {"steps.test6.outputs.status": "skipped",
                                                        "steps.test6.outputs.decision": decision})
                self.assertEqual(result.returncode, int(decision in ("not_configured", "baseline_failed")))

    def test_collector_still_rejects_original_five_pass_one_skip_all_green_api(self):
        summary, values, _ = self.run_checks()
        summary.update(passed="5", skipped="1")
        result, payload = self.collect(summary, values, ["success"] * 6)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ocm: emitted skipped count contradicts test details", result.stderr)
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
