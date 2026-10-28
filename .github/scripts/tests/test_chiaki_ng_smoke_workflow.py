"""Execute Chiaki's workflow and composite with offline transport/artifact fixtures."""

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
SCRIPTS = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))
import package_result_policy as policy


class ChiakiNgSmokeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="chiaki-workflow-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "tmp").mkdir()
        source = self.root / "baseline-src"
        source.mkdir()
        (source / "README.md").write_text("Chiaki-ng Qt SDL FFmpeg PlayStation\n")
        self.workflow = yaml.safe_load((ROOT / ".github/workflows/test-chiaki-ng.yml").read_text())
        self.job = self.workflow["jobs"]["test-chiaki-ng"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.action = yaml.safe_load((ROOT / ".github/actions/generic-source-regression-check/action.yml").read_text())
        self.env = {**os.environ, **self.job["env"], "PYTHONDONTWRITEBYTECODE": "1",
                    "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "GITHUB_OUTPUT": str(self.root / "outputs"), "CALLS": str(self.root / "calls"),
                    "GH_TOKEN": "offline-chiaki-token", "GITHUB_TOKEN": "offline-other-token"}
        self.values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
        self.values.update({f"steps.test{i}.outcome": "success" for i in range(1, 7)})
        self.values.update({"steps.install.outputs.install_mode": "github_source",
                            "steps.install.outputs.resolved_tag": "v1.9.3",
                            "steps.test6.outputs.decision": "limited_cpu_smoke_validated",
                            "steps.test6.outputs.regression_result": "Arm preflight proof passed on Arm64",
                            "steps.test6.outputs.comparison": self.steps["test6"]["with"]["limited_cpu_description"]})
        self.stub("curl", r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
url = next(a for a in args if a.startswith("https://"))
api = url.startswith("https://api.github.com/repos/streetpea/chiaki-ng/releases/tags/")
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps({"kind": "metadata" if api else "asset", "url": url}) + "\n")
if api:
    assert "-fsS" in args and "-fsSL" not in args
    assert not any(a in args for a in ("-L", "--location", "--location-trusted"))
    assert args[args.index("-H") + 1] == "Authorization: Bearer offline-chiaki-token"
    if os.environ.get("API_ERROR"):
        print("curl: (22) The requested URL returned error: " + os.environ["API_ERROR"], file=sys.stderr)
        sys.exit(22)
    if os.environ.get("BAD_JSON"):
        print("not JSON")
    else:
        assets = [] if os.environ.get("MISSING_ASSET") else [{"name": "chiaki-ng-arm64.AppImage",
                  "browser_download_url": "https://github.com/streetpea/chiaki-ng/releases/download/fixture/chiaki-ng-arm64.AppImage"}]
        print(json.dumps({"assets": assets}))
else:
    assert url == "https://github.com/streetpea/chiaki-ng/releases/download/fixture/chiaki-ng-arm64.AppImage"
    assert "-H" not in args and "--location-trusted" not in args
    assert "GH_TOKEN" not in os.environ and "GITHUB_TOKEN" not in os.environ
    if os.environ.get("ASSET_ERROR"):
        sys.exit(22)
    Path(args[args.index("-o") + 1]).write_text(os.environ["APPIMAGE_FIXTURE"])
''')
        self.env["APPIMAGE_FIXTURE"] = f"#!{sys.executable}\n" + r'''
import json, os, sys
from pathlib import Path
assert "GH_TOKEN" not in os.environ and "GITHUB_TOKEN" not in os.environ
assert sys.argv[1:] == ["--appimage-extract"]
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps({"kind": "extract"}) + "\n")
if os.environ.get("EXTRACT_ERROR"):
    sys.exit(7)
if not os.environ.get("MISSING_BINARY"):
    binary = Path("squashfs-root/usr/bin/chiaki")
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text('#!/bin/sh\n[ "${GH_TOKEN+x}" != x ] && [ "${GITHUB_TOKEN+x}" != x ] || exit 97\necho "chiaki usage options help"\nexit "${HELP_EXIT:-0}"\n')
    binary.chmod(0o755)
'''
        self.stub("file", r'''
import os, sys
from pathlib import Path
assert "GH_TOKEN" not in os.environ and "GITHUB_TOKEN" not in os.environ
assert Path(sys.argv[1]).is_file()
key = "IMAGE_ARCH" if sys.argv[1].endswith(".AppImage") else "BINARY_ARCH"
print(sys.argv[1] + ": ELF 64-bit " + os.environ.get(key, "ARM aarch64"))
''')
        self.stub("git", r'''
import os, sys
from pathlib import Path
if sys.argv[1] == "clone":
    if os.environ.get("CLONE_ERROR"):
        sys.exit(1)
    root = Path(sys.argv[-1])
    root.mkdir()
    (root / "README.md").write_text("unrelated" if os.environ.get("MISSING_MARKERS") else "Chiaki Qt SDL FFmpeg")
else:
    raise AssertionError("Unexpected fixture git invocation")
''')
        for command in ("timeout", "xvfb-run"):
            self.stub(command, 'import os, sys\nos.execvp(sys.argv[2], sys.argv[2:])\n')

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def render(self, text, values):
        def expression(match):
            terms = match[1].split("||")
            return values.get(terms[0].strip()) or (terms[1].strip().strip("'") if len(terms) > 1 else "")
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, text)

    def execute(self, script, env):
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        script = script.replace("/tmp/chiaki-ng", str(self.root / "tmp/chiaki-ng"))
        process = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
                                 env=env, text=True, capture_output=True, timeout=30)
        fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        for token in ("offline-chiaki-token", "offline-other-token"):
            self.assertNotIn(token, process.stdout + process.stderr + output.read_text())
        return process, fields

    def run_step(self, name, values=None, **environment):
        bindings = {**self.values, **(values or {})}
        step = self.steps[name]
        env = {**self.env, **environment}
        if name == "summary":
            env.update({k: self.render(v, bindings) for k, v in step["env"].items()})
        return self.execute(self.render(step["run"], bindings), env)

    def run_candidate(self, **environment):
        inputs = {name: str(data.get("default", "")) for name, data in self.action["inputs"].items()}
        inputs.update({k: self.render(str(v), self.values) for k, v in self.steps["test6"]["with"].items()})
        inputs.update(baseline_version="1.9.3", github_repo="streetpea/chiaki-ng",
                      lane_kind=self.job["env"]["LANE_KIND"],
                      next_version_override="1.10.0", candidate_tag_override="v1.10.0")
        # Exercise the real composite/probe with a fixed offline candidate, not tag discovery.
        bindings = {f"inputs.{key}": value for key, value in inputs.items()}
        step = self.action["runs"]["steps"][0]
        env = {**self.env, **{k: self.render(v, bindings) for k, v in step["env"].items()}, **environment}
        return self.execute(self.render(step["run"], bindings), env)

    def calls(self):
        path = self.root / "calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_permissions_triggers_and_credentials_are_step_scoped(self):
        self.assertEqual({"contents": "read"}, self.workflow["permissions"])
        self.assertIn("workflow_dispatch", self.workflow[True])
        self.assertIn("workflow_call", self.workflow[True])
        checkouts = [s for s in self.job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
        self.assertEqual(1, len(checkouts))
        self.assertFalse(checkouts[0]["with"]["persist-credentials"])
        self.assertNotIn("GH_TOKEN", self.job["env"])
        self.assertEqual(["test5", "test6"], [s["id"] for s in self.job["steps"] if "GH_TOKEN" in s.get("env", {})])
        for name in ("test5", "test6"):
            self.assertEqual({"GH_TOKEN": "${{ github.token }}"}, self.steps[name]["env"])
        self.assertFalse(self.steps["test6"]["with"].get("defer_on_limited_cpu_probe_failure", False))
        self.assertEqual("Test 6 - Regression Validation", self.steps["test6"]["name"])

    def test_baseline_and_real_composite_authenticate_only_metadata(self):
        for name in ("test5", "test6"):
            with self.subTest(step=name):
                process, fields = self.run_step(name) if name == "test5" else self.run_candidate()
                self.assertEqual(0, process.returncode, process.stdout + process.stderr)
                self.assertEqual("passed", fields["status"])
        calls = self.calls()
        self.assertEqual(["metadata", "asset", "extract"] * 2, [c["kind"] for c in calls])
        self.assertTrue(calls[0]["url"].endswith("/v1.9.3"))
        self.assertTrue(calls[3]["url"].endswith("/v1.10.0"))
        self.assertEqual("limited_cpu_smoke_validated", fields["decision"])

    def test_http_errors_and_missing_metadata_never_download_or_pass(self):
        for failure in ({"API_ERROR": "401"}, {"API_ERROR": "403"}, {"BAD_JSON": "1"}, {"MISSING_ASSET": "1"}, {"GH_TOKEN": ""}):
            for name in ("test5", "test6"):
                with self.subTest(step=name, failure=failure):
                    before = len(self.calls())
                    if name == "test5":
                        process, fields = self.run_step(name, **failure)
                        self.assertNotEqual(0, process.returncode)
                        self.assertNotEqual("passed", fields.get("status"))
                    else:
                        process, fields = self.run_candidate(**failure)
                        self.assertEqual(0, process.returncode, process.stderr)
                        self.assertEqual("failed", fields["status"])
                        self.assertEqual("limited_cpu_smoke_failed", fields["decision"])
                        result, summary = self.run_step("summary", {f"steps.test6.outputs.{k}": v for k, v in fields.items()})
                        self.assertNotEqual(0, result.returncode)
                        self.assertEqual(("5", "1", "0"), tuple(summary[k] for k in ("passed", "failed", "skipped")))
                    self.assertNotIn("asset", [c["kind"] for c in self.calls()[before:]])

    def test_artifact_and_architecture_failures_remain_required(self):
        for failure in ({"ASSET_ERROR": "1"}, {"IMAGE_ARCH": "x86-64"}, {"BINARY_ARCH": "x86-64"},
                        {"EXTRACT_ERROR": "1"}, {"MISSING_BINARY": "1"}, {"MISSING_MARKERS": "1"}, {"CLONE_ERROR": "1"}):
            with self.subTest(failure=failure):
                process, fields = self.run_candidate(**failure)
                self.assertEqual(0, process.returncode, process.stderr)
                self.assertEqual("failed", fields["status"])
                self.assertIn(fields["decision"], ("limited_cpu_smoke_failed", "next_install_failed"))

    def test_baseline_download_extraction_and_architecture_failures_are_not_masked(self):
        for failure in ({"ASSET_ERROR": "1"}, {"IMAGE_ARCH": "x86-64"}, {"BINARY_ARCH": "x86-64"},
                        {"EXTRACT_ERROR": "1"}, {"MISSING_BINARY": "1"}):
            with self.subTest(failure=failure):
                shutil.rmtree(self.root / "baseline-src/squashfs-root", ignore_errors=True)
                process, fields = self.run_step("test5", **failure)
                self.assertNotEqual(0, process.returncode)
                self.assertNotEqual("passed", fields.get("status"))
                result, summary = self.run_step("summary", {"steps.test5.outputs.status": fields.get("status", ""),
                    "steps.test5.outcome": "failure", "steps.test6.outcome": "skipped"})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("4", "1", "1"), tuple(summary[k] for k in ("passed", "failed", "skipped")))
                self.assertEqual("baseline_failed", summary["regression_decision"])

    def test_baseline_help_limitation_remains_explicit(self):
        process, fields = self.run_step("test5", HELP_EXIT="127")
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("passed", fields["status"])
        self.assertIn("headless --help was attempted but not required", fields["note"])
        self.assertNotIn("headless --help completed", fields["note"])
        self.assertIn("real stream decode were not claimed", fields["note"])

    def test_summary_pass_and_approved_skips_preserve_exact_counts(self):
        for status, decision in (("passed", "limited_cpu_smoke_validated"),
                                 ("skipped", "no_newer_stable_available")):
            process, fields = self.run_step("summary", {"steps.test6.outputs.status": status,
                                                        "steps.test6.outputs.decision": decision})
            self.assertEqual(0, process.returncode, process.stderr)
            expected = ("6", "0", "0") if status == "passed" else ("5", "0", "1")
            self.assertEqual(expected, tuple(fields[k] for k in ("passed", "failed", "skipped")))
            self.assertEqual(decision, fields["regression_decision"])
            self.assertEqual(status, fields["regression_status"])
            self.assertEqual(self.values["steps.test6.outputs.comparison"], fields["regression_comparison"])
            self.assertEqual("success", self.validate_summary(fields, ["passed"] * 5))

    def validate_summary(self, fields, baseline):
        details = [{"name": f"Test {i} - fixture", "status": status} for i, status in enumerate(baseline, 1)]
        details.append({"name": "Test 6 - Regression Validation", "status": fields["regression_status"],
                        "decision": fields["regression_decision"]})
        return policy.validate_six_test_result(details=details, decision=fields["regression_decision"],
            **{k: int(fields[k]) for k in ("passed", "failed", "skipped", "core_failed")})

    def test_summary_missing_invalid_or_contradictory_candidate_fails_closed(self):
        cases = [{"steps.test6.outputs.status": status, "steps.test6.outputs.decision": decision}
                 for status, decision in (("", ""), ("skipped", ""), ("passed", ""),
                    ("skipped", "not_applicable_package_manager"), ("passed", "no_newer_stable_available"),
                    ("skipped", "limited_cpu_smoke_failed"), ("passed", "next_install_validated"),
                    ("skipped", "metadata_review_required"), ("skipped", "runtime_validation_not_automated"),
                    ("skipped", "invented"), ("failed", "limited_cpu_smoke_failed"))]
        cases += [{"steps.test6.outcome": outcome} for outcome in ("failure", "skipped", "cancelled", "")]
        for values in cases:
            with self.subTest(values=values):
                process, fields = self.run_step("summary", values)
                self.assertNotEqual(0, process.returncode)
                self.assertEqual(("5", "1", "0", "0"), tuple(fields[k] for k in ("passed", "failed", "skipped", "core_failed")))
                self.assertEqual("failure", self.validate_summary(fields, ["passed"] * 5))

    def test_deferred_candidate_is_failed_without_erasing_lookup_explanation(self):
        for decision in ("metadata_review_required", "runtime_validation_not_automated"):
            with self.subTest(decision=decision):
                values = {"steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": decision,
                          "steps.test6.outputs.regression_result": "Automatic next-version resolution needs manual review",
                          "steps.test6.outputs.comparison": "Comparable stable version tags could not be derived."}
                process, fields = self.run_step("summary", values)
                self.assertNotEqual(0, process.returncode)
                self.assertEqual("next_regression_failed", fields["regression_decision"])
                self.assertEqual("failed", fields["regression_status"])
                self.assertIn(values["steps.test6.outputs.regression_result"], fields["regression_result"])
                self.assertIn(values["steps.test6.outputs.comparison"], fields["regression_comparison"])
                collected, payload = self.collect(fields, values, ["success"] * 6)
                self.assertEqual(0, collected.returncode, collected.stdout + collected.stderr)
                self.assertEqual("failure", policy.validate_publishable_result(payload))
                self.assertEqual((5, 1, 0), tuple(payload["tests"][k] for k in ("passed", "failed", "skipped")))

    def test_missing_or_failed_baseline_is_failure_and_candidate_is_gated(self):
        condition = self.steps["test6"]["if"]
        for i in range(1, 6):
            self.assertIn(f"steps.test{i}.outcome == 'success'", condition)
            self.assertIn(f"steps.test{i}.outputs.status == 'passed'", condition)
            for key, value in (("outputs.status", ""), ("outputs.status", "skipped"),
                               ("outputs.status", "failed"), ("outcome", "failure"), ("outcome", "skipped")):
                with self.subTest(test=i, key=key, value=value):
                    values = {f"steps.test{i}.{key}": value, "steps.test6.outcome": "skipped"}
                    process, fields = self.run_step("summary", values)
                    self.assertNotEqual(0, process.returncode)
                    self.assertEqual(("4", "1", "1", "1"), tuple(fields[k] for k in ("passed", "failed", "skipped", "core_failed")))
                    self.assertEqual("baseline_failed", fields["regression_decision"])
                    baseline = ["passed"] * 5
                    baseline[i - 1] = "failed"
                    self.assertEqual("failure", self.validate_summary(fields, baseline))
        values = {f"steps.test{i}.outputs.status": "" for i in range(1, 6)}
        process, fields = self.run_step("summary", values)
        self.assertNotEqual(0, process.returncode)
        self.assertEqual(("0", "5", "1", "5"), tuple(fields[k] for k in ("passed", "failed", "skipped", "core_failed")))

    def collect(self, summary, values, conclusions):
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        bindings = {**self.values, **values, **{f"steps.summary.outputs.{k}": v for k, v in summary.items()},
                    "steps.version.outputs.version": "1.9.3", "steps.metadata.outputs.package_slug": "chiaki-ng",
                    "steps.metadata.outputs.dashboard_link": "/linux/opensource_packages/chiaki-ng",
                    "steps.metadata.outputs.timestamp": "2026-10-27T22:17:27Z",
                    "github.run_id": "123", "github.run_attempt": "1", "github.job": "test-chiaki-ng"}
        outputs = {k: self.render(str(v), bindings) for k, v in self.job["outputs"].items()}
        job = {"id": 456, "name": "test-chiaki-ng / test-chiaki-ng", "conclusion": summary["overall_status"],
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "steps": [{"name": self.steps[f"test{i}"]["name"], "number": i, "conclusion": status}
                         for i, status in enumerate(conclusions, 1)]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(SCRIPTS)
            process = subprocess.run([sys.executable, "-B", "-c", source], cwd=root,
                env={**self.env, "NEEDS_JSON": json.dumps({"test-chiaki-ng": {"result": summary["overall_status"], "outputs": outputs}}),
                     "RUN_JOBS_JSON": json.dumps({"jobs": [job]}), "BATCH_NUMBER": "5", "BATCH_TITLE": "Batch 5",
                     "GH_TOKEN": "", "GITHUB_TOKEN": "", "GITHUB_SERVER_URL": "https://github.com",
                     "GITHUB_STEP_SUMMARY": str(root / "summary"),
                     "GITHUB_API_URL": "https://api.github.com", "GITHUB_REPOSITORY": "example/project",
                     "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"},
                capture_output=True, text=True, timeout=30)
            path = root / "test-results/chiaki-ng-test-results/chiaki-ng.json"
            return process, json.loads(path.read_text()) if path.exists() else None

    def test_active_collector_retains_candidate_scope_and_failure_evidence(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                _, regression = self.run_candidate(**({"API_ERROR": "403"} if failed else {}))
                values = {f"steps.test6.outputs.{k}": v for k, v in regression.items()}
                result, summary = self.run_step("summary", values)
                self.assertEqual(failed, result.returncode != 0)
                collected, payload = self.collect(summary, values, ["success"] * 6)
                self.assertEqual(0, collected.returncode, collected.stdout + collected.stderr)
                self.assertEqual("failure" if failed else "success", policy.validate_publishable_result(payload))
                self.assertEqual((5, 1, 0) if failed else (6, 0, 0), tuple(payload["tests"][k] for k in ("passed", "failed", "skipped")))
                detail = payload["tests"]["details"][5]
                self.assertEqual("Test 6 - Regression Validation", detail["name"])
                for key in ("decision", "regression_result", "comparison", "current_version", "latest_version", "next_installed_version"):
                    self.assertEqual(regression[key], detail[key])
                self.assertIn("does not prove PS4/PS5", detail["comparison"])

    def test_active_collector_records_baseline_guard_and_rejects_contradictory_steps(self):
        values = {"steps.test5.outputs.status": "", "steps.test5.outcome": "failure", "steps.test6.outcome": "skipped"}
        _, summary = self.run_step("summary", values)
        process, payload = self.collect(summary, values, ["success"] * 4 + ["failure", "skipped"])
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        self.assertEqual((4, 1, 1), tuple(payload["tests"][k] for k in ("passed", "failed", "skipped")))
        self.assertEqual("baseline_failed", payload["tests"]["details"][5]["decision"])
        self.assertEqual("failure", policy.validate_publishable_result(payload))
        process, payload = self.collect(summary, values, ["success"] * 5 + ["skipped"])
        self.assertNotEqual(0, process.returncode)
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
