"""Execute cuDNN FE workflow logic with offline, synthetic source/API fixtures.

The baseline Test 5 probe uses the local C++ compiler and Python, but stubs
uname. These tests are not native Arm, upstream-source, wheel, cuDNN runtime,
or GPU validation. Test 6 coverage here is limited to its summary contract.
"""

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
import promote_package_results as publisher

WORKFLOW = ROOT / ".github/workflows/test-cudnn-fe.yml"
JOB = "test-cudnn-fe"
CANDIDATE = "1.32.1"
SCOPE = "Offline fixture: CPU-side preflight only; no cuDNN library load or GPU execution is claimed."


class CudnnFeSmokeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cudnn-fe-workflow-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.job = self.workflow["jobs"][JOB]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.baseline = self.job["env"]["BASELINE_VERSION"]
        self.regression = {
            "status": "passed", "decision": "limited_cpu_smoke_validated",
            "regression_result": "Offline fixture: version header and Python sources compiled.",
            "comparison": SCOPE, "current_version": self.baseline,
            "latest_version": CANDIDATE, "next_installed_version": CANDIDATE,
        }
        self.values = {
            f"steps.test{i}.{key}": value for i in range(1, 7)
            for key, value in (("outputs.status", "passed"), ("outcome", "success"),
                               ("outputs.duration", str(i)))
        }
        self.values.update(self.regression_values(self.regression))

    @staticmethod
    def regression_values(regression):
        return {f"steps.test6.outputs.{key}": value for key, value in regression.items()}

    def render(self, source, overrides=None):
        values = {**self.values, **(overrides or {})}

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else values.get(term, "")
                if value:
                    return str(value)
            return ""

        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, str(source))

    def run_summary(self, values=None):
        return self.run_step("summary", values)

    def run_step(self, name, values=None, *, cwd=None, **environment):
        self.output.write_text("")
        step = self.steps[name]
        env = {**os.environ, **self.job["env"], "GITHUB_OUTPUT": str(self.output),
               **{key: self.render(value, values) for key, value in step.get("env", {}).items()},
               **environment}
        result = subprocess.run(
            ["/bin/bash", "-e", "-o", "pipefail", "-c", self.render(step["run"], values)],
            cwd=cwd or self.root, env=env, text=True, capture_output=True, timeout=30,
        )
        fields = dict(line.split("=", 1) for line in self.output.read_text().splitlines())
        return result, fields

    def assert_summary(self, result, fields, counts, *, core_failed=0,
                       status="passed", decision="limited_cpu_smoke_validated", duration=21):
        expected = "failure" if counts[1] else "success"
        if expected == "success":
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        else:
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(tuple(map(str, counts)),
                         tuple(fields[key] for key in ("passed", "failed", "skipped")))
        self.assertEqual(6, sum(int(fields[key]) for key in ("passed", "failed", "skipped")))
        self.assertEqual(str(core_failed), fields["core_failed"])
        self.assertEqual(str(duration), fields["duration"])
        self.assertEqual(expected, fields["overall_status"])
        self.assertEqual("failing" if counts[1] else "passing", fields["badge_status"])
        self.assertEqual(status, fields["regression_status"])
        self.assertEqual(decision, fields["regression_decision"])
        self.assertTrue(fields["regression_result"].strip())

    def test_summary_accepts_six_real_passes(self):
        result, fields = self.run_summary()
        self.assert_summary(result, fields, (6, 0, 0))
        self.assertEqual(self.regression["regression_result"], fields["regression_result"])
        self.assertEqual(SCOPE, fields["regression_comparison"])

    def test_summary_accepts_five_passes_and_genuine_no_newer_skip(self):
        regression = {**self.regression, "status": "skipped",
                      "decision": "no_newer_stable_available",
                      "regression_result": "Offline fixture: complete stable inventory has no newer release.",
                      "comparison": "Offline fixture: latest stable equals the baseline.",
                      "latest_version": self.baseline, "next_installed_version": "n/a"}
        result, fields = self.run_summary(self.regression_values(regression))
        self.assert_summary(result, fields, (5, 0, 1), status="skipped",
                            decision="no_newer_stable_available")
        self.assertEqual(regression["regression_result"], fields["regression_result"])
        self.assertEqual(regression["comparison"], fields["regression_comparison"])

    def test_failed_test6_status_fails_even_when_github_step_succeeds(self):
        result, fields = self.run_summary({"steps.test6.outputs.status": "failed",
                                          "steps.test6.outputs.decision": "limited_cpu_smoke_failed"})
        self.assert_summary(result, fields, (5, 1, 0), status="failed",
                            decision="limited_cpu_smoke_failed")

    def test_each_baseline_requires_a_successful_github_outcome(self):
        for index in range(1, 6):
            for outcome in ("failure", "cancelled", "skipped", "", None):
                with self.subTest(index=index, outcome=outcome):
                    result, fields = self.run_summary({f"steps.test{index}.outcome": outcome})
                    self.assert_summary(result, fields, (4, 1, 1), core_failed=1,
                                        status="skipped", decision="baseline_failed")

    def test_each_baseline_requires_explicit_valid_pass_evidence(self):
        for index in range(1, 6):
            for status in (None, "", " \t ", "invalid", "failed", "skipped"):
                with self.subTest(index=index, status=status):
                    result, fields = self.run_summary({f"steps.test{index}.outputs.status": status})
                    self.assert_summary(result, fields, (4, 1, 1), core_failed=1,
                                        status="skipped", decision="baseline_failed")

    def test_core_failures_override_even_positive_or_failed_candidate_evidence(self):
        for status, decision in (("passed", "limited_cpu_smoke_validated"),
                                 ("skipped", "no_newer_stable_available"),
                                 ("failed", "limited_cpu_smoke_failed")):
            with self.subTest(status=status):
                values = {f"steps.test{i}.outputs.status": "failed" for i in range(1, 6)}
                values.update({"steps.test6.outputs.status": status,
                               "steps.test6.outputs.decision": decision})
                result, fields = self.run_summary(values)
                self.assert_summary(result, fields, (0, 5, 1), core_failed=5,
                                    status="skipped", decision="baseline_failed")
                self.assertNotEqual(SCOPE, fields["regression_comparison"])

    def test_candidate_positive_branches_require_a_successful_github_outcome(self):
        for status, decision in (("passed", "limited_cpu_smoke_validated"),
                                 ("skipped", "no_newer_stable_available")):
            for outcome in ("failure", "cancelled", "skipped", "", None):
                with self.subTest(status=status, outcome=outcome):
                    result, fields = self.run_summary({"steps.test6.outputs.status": status,
                        "steps.test6.outputs.decision": decision, "steps.test6.outcome": outcome})
                    self.assert_summary(result, fields, (5, 1, 0), status="failed",
                                        decision="next_regression_failed")

    def test_candidate_missing_invalid_and_contradictory_evidence_fails_closed(self):
        cases = [(status, "limited_cpu_smoke_validated")
                 for status in (None, "", " \t ", "invalid", "failed", "skipped")]
        cases += [("passed", decision) for decision in (None, "", " \t ", "invalid",
                    "no_newer_stable_available", "metadata_review_required")]
        cases += [("skipped", decision) for decision in (None, "", " \t ", "invalid",
                    "metadata_review_required", "not_applicable_package_manager")]
        for status, decision in cases:
            with self.subTest(status=status, decision=decision):
                result, fields = self.run_summary({"steps.test6.outputs.status": status,
                                                  "steps.test6.outputs.decision": decision})
                self.assert_summary(result, fields, (5, 1, 0), status="failed",
                                    decision="next_regression_failed")

    def test_both_positive_branches_require_nonblank_result_and_comparison(self):
        for status, decision in (("passed", "limited_cpu_smoke_validated"),
                                 ("skipped", "no_newer_stable_available")):
            for key in ("regression_result", "comparison"):
                for value in (None, "", " \t "):
                    with self.subTest(status=status, key=key, value=value):
                        result, fields = self.run_summary({"steps.test6.outputs.status": status,
                            "steps.test6.outputs.decision": decision, f"steps.test6.outputs.{key}": value})
                        self.assert_summary(result, fields, (5, 1, 0), status="failed",
                                            decision="next_regression_failed")

    def test_summary_duration_defaults_missing_values_to_zero(self):
        values = {f"steps.test{i}.outputs.duration": None for i in range(1, 7)}
        result, fields = self.run_summary(values)
        self.assert_summary(result, fields, (6, 0, 0), duration=0)
        values["steps.test3.outputs.duration"] = "17"
        values["steps.test6.outputs.duration"] = "8"
        result, fields = self.run_summary(values)
        self.assert_summary(result, fields, (6, 0, 0), duration=25)

    def test_summary_evidence_is_passed_through_environment_not_shell_source(self):
        evidence = 'Offline fixture: "quoted" $(touch injected) `touch injected`'
        result, fields = self.run_summary({"steps.test6.outputs.regression_result": evidence,
                                          "steps.test6.outputs.comparison": evidence})
        self.assert_summary(result, fields, (6, 0, 0))
        self.assertEqual(evidence, fields["regression_result"])
        self.assertEqual(evidence, fields["regression_comparison"])
        self.assertFalse((self.root / "injected").exists())

    def test_job_outputs_bind_to_normalized_summary_not_raw_candidate(self):
        _, summary = self.run_summary({"steps.test1.outputs.status": "failed"})
        bindings = {f"steps.summary.outputs.{key}": value for key, value in summary.items()}
        outputs = {key: self.render(value, bindings) for key, value in self.job["outputs"].items()}
        expected = {"run_status": "overall_status", "badge_status": "badge_status",
                    "core_failed": "core_failed", "tests_passed": "passed", "tests_failed": "failed",
                    "tests_skipped": "skipped", "duration_seconds": "duration",
                    **{f"regression_{key}": f"regression_{key}"
                       for key in ("status", "decision", "result", "comparison")}}
        for output, field in expected.items():
            with self.subTest(output=output):
                self.assertIn(f"steps.summary.outputs.{field}", self.job["outputs"][output])
                self.assertEqual(summary[field], outputs[output])
        self.assertEqual("skipped", outputs["regression_status"])
        self.assertEqual("baseline_failed", outputs["regression_decision"])

    def test_test6_is_gated_on_all_five_core_outcomes_and_statuses(self):
        condition = self.steps["test6"]["if"].strip().removeprefix("${{").removesuffix("}}")
        clauses = [clause.strip() for clause in condition.split("&&")]
        expected = ["success()"] + [clause for index in range(1, 6) for clause in
                    (f"steps.test{index}.outcome == 'success'",
                     f"steps.test{index}.outputs.status == 'passed'")]
        self.assertCountEqual(expected, clauses)
        self.assertEqual("always()", self.steps["summary"]["if"])
        self.assertNotIn("continue-on-error", self.steps["summary"])

    def test_test6_runs_wheel_helper_and_propagates_its_exit_status(self):
        step = self.steps["test6"]
        self.assertNotIn("uses", step)
        self.assertNotIn("continue-on-error", step)
        self.assertGreater(step["timeout-minutes"], 0)
        self.assertLessEqual(step["timeout-minutes"], 10)
        binaries = self.root / "fixture-bin"
        binaries.mkdir()
        python = binaries / "python3"
        python.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$FIXTURE_ARGS"\n'
                          'exit "$FIXTURE_EXIT"\n')
        python.chmod(0o755)
        arguments = self.root / "helper-arguments"
        for code in (0, 23):
            with self.subTest(exit_status=code):
                result, _ = self.run_step(
                    "test6", {"steps.version.outputs.version": self.baseline},
                    PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                    FIXTURE_ARGS=str(arguments), FIXTURE_EXIT=str(code),
                )
                self.assertEqual(code, result.returncode, result.stdout + result.stderr)
                self.assertEqual([".github/scripts/cudnn_frontend_wheel_smoke.py",
                                  "--baseline-version", self.baseline], arguments.read_text().splitlines())

    def run_baseline_probe_fixture(self, *, header_version=None, machine="aarch64",
                                   missing_macro=None, python_source="value = 1\n",
                                   invalid_cpp=False, install_mode="github_source",
                                   missing_path=None, aggregate_header="#include <cudnn.h>\n"):
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("A real g++-compatible compiler is required for the synthetic header fixture")
        version = (header_version or self.baseline).lstrip("v")
        with tempfile.TemporaryDirectory(prefix="baseline-source-fixture-", dir=self.root) as temporary:
            fixture_root = Path(temporary)
            source = fixture_root / "baseline-src"
            (source / "include").mkdir(parents=True)
            (source / "python/cudnn").mkdir(parents=True)
            (source / "include/cudnn_frontend.h").write_text(aggregate_header)
            macros = dict(zip(("MAJOR", "MINOR", "PATCH"), version.split(".")))
            header = "// Synthetic fixture, not an upstream package checkout.\n#pragma once\n"
            header += "".join(f"#define CUDNN_FRONTEND_{name}_VERSION {value}\n"
                              for name, value in macros.items() if name != missing_macro)
            # Keep the aggregate independent so missing components reach the Python check.
            if missing_macro != "AGGREGATE":
                number = int(macros["MAJOR"]) * 10000 + int(macros["MINOR"]) * 100 + int(macros["PATCH"])
                header += f"#define CUDNN_FRONTEND_VERSION {number}\n"
            if invalid_cpp:
                header += "this is not valid C++;\n"
            (source / "include/cudnn_frontend_version.h").write_text(header)
            (source / "python/cudnn/__init__.py").write_text(python_source)
            if missing_path:
                path = source / missing_path
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            binaries = fixture_root / "fixture-bin"
            binaries.mkdir()
            uname = binaries / "uname"
            uname.write_text('#!/bin/bash\n[ "$1" = "-m" ] || exit 64\n'
                             'printf "%s\\n" "$FIXTURE_MACHINE"\n')
            uname.chmod(0o755)
            (binaries / "g++").symlink_to(compiler)
            (binaries / "python3").symlink_to(sys.executable)
            return self.run_step(
                "test5", {"steps.install.outputs.install_mode": install_mode}, cwd=fixture_root,
                PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                FIXTURE_MACHINE=machine, PYTHONDONTWRITEBYTECODE="1",
            )

    def assert_baseline_rejected(self, result, fields):
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotEqual("passed", fields.get("status"))
        self.assertNotIn("preflight-ok", result.stdout)

    def test_baseline_test5_compiles_synthetic_matching_header_and_python_sources(self):
        result, fields = self.run_baseline_probe_fixture()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", fields["status"])
        self.assertTrue(fields["duration"].isdigit())
        self.assertIn(f"header version {self.baseline.lstrip('v')} and Python sources compiled", result.stdout)
        self.assertIn("no cuDNN library or GPU execution is claimed", fields["note"])

    def test_baseline_test5_rejects_header_version_mismatch_without_relaxation(self):
        version = self.baseline.lstrip("v")
        major, minor, patch = map(int, version.split("."))
        mismatch = f"{major}.{minor}.{patch + 1}"
        result, fields = self.run_baseline_probe_fixture(header_version=mismatch)
        self.assert_baseline_rejected(result, fields)
        self.assertIn(f"header version {mismatch} != expected {version}", result.stderr)

    def test_baseline_test5_rejects_missing_version_macros(self):
        for macro in ("MAJOR", "MINOR", "PATCH", "AGGREGATE"):
            with self.subTest(macro=macro):
                result, fields = self.run_baseline_probe_fixture(missing_macro=macro)
                self.assert_baseline_rejected(result, fields)
                if macro == "AGGREGATE":
                    self.assertIn("CUDNN_FRONTEND_VERSION missing", result.stderr)
                else:
                    self.assertIn(f"missing cuDNN Frontend {macro} version macro", result.stderr)

    def test_baseline_test5_rejects_python_compilation_failure(self):
        result, fields = self.run_baseline_probe_fixture(python_source="def broken(:\n")
        self.assert_baseline_rejected(result, fields)
        self.assertIn("compileall failed for python/cudnn", result.stderr)

    def test_baseline_test5_rejects_invalid_cpp_with_real_compiler(self):
        result, fields = self.run_baseline_probe_fixture(invalid_cpp=True)
        self.assert_baseline_rejected(result, fields)
        self.assertIn("error:", result.stderr)

    def test_baseline_test5_rejects_wrong_architecture(self):
        result, fields = self.run_baseline_probe_fixture(machine="x86_64")
        self.assert_baseline_rejected(result, fields)

    def test_baseline_test5_requires_source_install_not_metadata_only(self):
        for mode in ("external_artifact", "unresolved", ""):
            with self.subTest(mode=mode):
                result, fields = self.run_baseline_probe_fixture(install_mode=mode)
                self.assert_baseline_rejected(result, fields)
                self.assertEqual("failed", fields["status"])
                self.assertIn("metadata-only evidence is not treated as a smoke pass", fields["note"])

    def test_baseline_test5_requires_headers_and_python_source_directory(self):
        for path in ("include/cudnn_frontend.h", "include/cudnn_frontend_version.h", "python/cudnn"):
            with self.subTest(path=path):
                result, fields = self.run_baseline_probe_fixture(missing_path=path)
                self.assert_baseline_rejected(result, fields)

    def test_baseline_test5_requires_cudnn_runtime_header_boundary(self):
        result, fields = self.run_baseline_probe_fixture(aggregate_header="#pragma once\n")
        self.assert_baseline_rejected(result, fields)

    def collect(self, summary, regression, *, job_conclusion, candidate_conclusion="success"):
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        bindings = {**self.regression_values(regression),
                    **{f"steps.summary.outputs.{key}": value for key, value in summary.items()},
                    "steps.version.outputs.version": self.baseline,
                    "steps.metadata.outputs.package_slug": "cudnn-fe",
                    "steps.metadata.outputs.dashboard_link": "/linux/opensource_packages/cudnn-fe",
                    "steps.metadata.outputs.timestamp": "2026-11-02T16:01:00Z",
                    "github.run_id": "123", "github.run_attempt": "1", "github.job": JOB}
        outputs = {key: self.render(value, bindings) for key, value in self.job["outputs"].items()}
        job = {"id": 456, "name": f"{JOB} / {JOB}", "conclusion": job_conclusion,
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "started_at": "2026-11-02T16:00:00Z", "completed_at": "2026-11-02T16:01:00Z",
               "steps": [{"name": self.steps[f"test{i}"]["name"], "number": i,
                          "conclusion": candidate_conclusion if i == 6 else "success",
                          "started_at": "2026-11-02T16:00:00Z",
                          "completed_at": f"2026-11-02T16:00:0{i}Z"} for i in range(1, 7)]}
        with tempfile.TemporaryDirectory(prefix="cudnn-fe-collector-fixture-") as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(SCRIPTS)
            process = subprocess.run(
                [sys.executable, "-B", "-c", source], cwd=root,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                     "GITHUB_OUTPUT": str(root / "output"),
                     "NEEDS_JSON": json.dumps({JOB: {"result": job_conclusion, "outputs": outputs}}),
                     "RUN_JOBS_JSON": json.dumps({"jobs": [job]}),
                     "BATCH_NUMBER": "9", "BATCH_TITLE": "Batch 9",
                     "GH_TOKEN": "", "GITHUB_TOKEN": "", "GITHUB_SERVER_URL": "https://github.com",
                     "GITHUB_STEP_SUMMARY": str(root / "summary"),
                     "GITHUB_API_URL": "https://api.github.com", "GITHUB_REPOSITORY": "example/project",
                     "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"},
                capture_output=True, text=True, timeout=30,
            )
            path = root / "test-results/cudnn-fe-test-results/cudnn-fe.json"
            payload = json.loads(path.read_text()) if path.exists() else None
        registration = {"batch_title": "Batch 9", "workflow_path": ".github/workflows/test-all-packages-batch9.yml",
                        "run_id": "123", "run_attempt": "1", "job_name": job["name"], "job_url": job["html_url"],
                        "job_conclusion": job_conclusion, "job_started_at": job["started_at"],
                        "job_completed_at": job["completed_at"], "resolution_status": "central_exact"}
        return process, payload, registration

    def test_collector_and_strict_publisher_roundtrip_pass_skip_and_failed_test6(self):
        for status, decision, job_conclusion, counts in (
                ("passed", "limited_cpu_smoke_validated", "success", (6, 0, 0)),
                ("skipped", "no_newer_stable_available", "success", (5, 0, 1)),
                ("failed", "limited_cpu_smoke_failed", "failure", (5, 1, 0))):
            with self.subTest(status=status):
                regression = {**self.regression, "status": status, "decision": decision}
                if status == "skipped":
                    regression.update(latest_version=self.baseline, next_installed_version="n/a",
                                      regression_result="Offline fixture: no newer stable release found.")
                elif status == "failed":
                    regression.update(next_installed_version="not_installed",
                                      regression_result="Offline fixture: candidate preflight failed.")
                # Guard contradictory evidence: Test 6 reports failure while
                # its GitHub step succeeds; the summary must fail the job.
                result, summary = self.run_summary(self.regression_values(regression))
                self.assert_summary(result, summary, counts, status=status, decision=decision)
                process, payload, registration = self.collect(summary, regression,
                                                               job_conclusion=job_conclusion)
                self.assertEqual(0, process.returncode, process.stdout + process.stderr)
                self.assertIsNotNone(payload)
                self.assertEqual(counts, tuple(payload["tests"][key] for key in ("passed", "failed", "skipped")))
                self.assertEqual(21, payload["tests"]["duration_seconds"])
                details = payload["tests"]["details"]
                self.assertEqual(6, len(details))
                self.assertEqual(list(range(1, 7)), [detail["duration_seconds"] for detail in details])
                self.assertEqual(["passed"] * 5 + [status], [detail["status"] for detail in details])
                self.assertEqual(decision, details[5]["decision"])
                self.assertIn(SCOPE, details[5]["comparison"])
                self.assertEqual(job_conclusion, payload["run"]["status"])
                self.assertEqual(job_conclusion, policy.validate_publishable_result(payload))
                self.assertEqual(job_conclusion, publisher.validate_persisted_result(
                    payload, expected_slug="cudnn-fe", expected_repository="example/project",
                    expected_registration=registration, publication_role="candidate",
                    validation_policy="strict", allow_legacy_missing_decision=False))


if __name__ == "__main__":
    unittest.main()
