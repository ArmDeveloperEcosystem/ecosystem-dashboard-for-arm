"""Feast installed retrieval, exact release identity, and failure accounting."""

import contextlib
from datetime import datetime
from importlib.metadata import PackageNotFoundError
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as audit


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-feast.yml"
POLICY_SPEC = importlib.util.spec_from_file_location(
    "feast_result_policy", WORKFLOW.parents[1] / "scripts/package_result_policy.py")
POLICY = importlib.util.module_from_spec(POLICY_SPEC)
POLICY_SPEC.loader.exec_module(POLICY)


class Column(list):
    @property
    def iloc(self):
        return self


class FeatureFrame(dict):
    def __len__(self):
        return len(self["driver_id"])


class FeastWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-feast"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        temporary = tempfile.TemporaryDirectory(prefix="feast-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.baseline = self.job["env"]["BASELINE_VERSION"]
        self.commit = self.job["env"]["BASELINE_SOURCE_COMMIT"]

    def python_body(self, key):
        return re.search(r"^python - <<'PY'\n(.*?)^PY$", self.job["env"][key], re.M | re.S)[1]

    def run_step(self, name, values=None, **environment):
        values = values or {}

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term.strip("'")
                if values.get(term):
                    return values[term]
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[name]["run"])
        step_env = {key: re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, value)
                    for key, value in self.steps[name].get("env", {}).items()}
        output = self.root / "output"
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
            env={**os.environ, **self.job["env"], "GITHUB_OUTPUT": str(output),
                 "GITHUB_WORKSPACE": str(WORKFLOW.parents[2]), **step_env, **environment},
            capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines() if line)

    def statuses(self):
        return {f"steps.test{i}.{key}": value for i in range(1, 7)
                for key, value in (("outputs.status", "passed"), ("outcome", "success"))}

    def stub_commands(self):
        binary = self.root / "bin"
        binary.mkdir(exist_ok=True)
        (binary / "python").symlink_to(sys.executable)
        runtime = self.root / "feast-baseline-venv/bin"
        runtime.mkdir(parents=True)
        (runtime / "activate").write_text(f'export PATH="{runtime}:$PATH"\n')
        commands = {
            binary / "git": '#!/bin/sh\nif [ "${GIT_RC:-0}" != 0 ]; then exit "$GIT_RC"; fi\ncase "$*" in\n'
                'clone*) mkdir -p next-src; touch next-src/README.md; exit "${CLONE_RC:-0}" ;;\n'
                '*refs/tags/*) echo "$TAG_COMMIT" ;;\n'
                '*) echo "$HEAD_COMMIT" ;;\nesac\n',
            binary / "uname": '#!/bin/sh\necho aarch64\n',
            binary / "timeout": '#!/bin/sh\nshift\nexec "$@"\n',
            runtime / "python": '#!/bin/sh\nexit "${PYTHON_RC:-0}"\n',
            runtime / "feast": '#!/bin/sh\nif [ "$1" = version ]; then\n'
                'printf \'Feast SDK Version: "feast %s"\\n\' "$CLI_VERSION"\n'
                'else printf "apply\\nmaterialize\\n"; fi\nexit "${CLI_RC:-0}"\n',
        }
        for path, script in commands.items():
            path.write_text(script)
            path.chmod(0o755)
        return {"PATH": str(binary) + os.pathsep + os.environ["PATH"],
                "HEAD_COMMIT": self.commit, "TAG_COMMIT": self.commit,
                "CLI_VERSION": self.baseline, "FEAST_VERIFY_COMMAND": "true"}

    def verify_identity(self, expected="0.10.4", metadata="0.10.4", module_version="0.10.4", location=None):
        module = SimpleNamespace(__version__=module_version,
            __file__=str(location or Path(sys.prefix) / "lib/feast/__init__.py"))
        lookup = {"side_effect": metadata} if isinstance(metadata, Exception) else {"return_value": metadata}
        with patch.dict(os.environ, SMOKE_VERSION=expected), patch.dict("sys.modules", feast=module), \
                patch("importlib.metadata.version", **lookup), contextlib.redirect_stdout(io.StringIO()):
            exec(compile(self.python_body("FEAST_VERIFY_COMMAND"), "feast-version", "exec"), {})

    def execute_runtime(self, expected="0.10.4", historical=(4.5,), online=(4.5,), sqlite_rows=2, failure=None):
        frame = FeatureFrame(driver_id=Column([1] * len(historical)), driver_ratings__rating=Column(historical))
        store = Mock()
        store.get_historical_features.return_value.to_df.return_value = frame
        store.get_online_features.return_value.to_dict.return_value = {"driver_ratings__rating": list(online)}
        if failure:
            store.get_historical_features.side_effect = failure

        def feature_store(repo_path):
            self.runtime_root = Path(repo_path)

            def apply(objects):
                with contextlib.closing(sqlite3.connect(self.runtime_root / "online.db")) as connection:
                    connection.execute("CREATE TABLE smoke_driver_ratings (feature_name TEXT)")
                    connection.executemany("INSERT INTO smoke_driver_ratings VALUES (?)", [("rating",)] * sqlite_rows)
                    connection.commit()
            store.apply.side_effect = apply
            return store

        feast = SimpleNamespace(Entity=Mock(), FeatureStore=feature_store, FeatureView=Mock(),
            FileSource=Mock(), Feature=Mock(), Field=Mock(), ValueType=SimpleNamespace(INT64=4, FLOAT=6))
        types = SimpleNamespace(Float32=6, Int64=SimpleNamespace(to_value_type=lambda: 4))
        pandas = SimpleNamespace(DataFrame=Mock(return_value=Mock()), to_datetime=Mock(),
            Timestamp=Mock(return_value=SimpleNamespace(to_pydatetime=lambda: datetime(2024, 1, 3))))
        self.printed = io.StringIO()
        with patch.dict(os.environ, SMOKE_VERSION=expected), \
                patch.dict("sys.modules", feast=feast, pandas=pandas, **{"feast.types": types}), \
                patch("importlib.metadata.version", return_value=expected), contextlib.redirect_stdout(self.printed):
            exec(compile(self.python_body("FEAST_SMOKE_COMMAND"), "feast-runtime", "exec"), {})
        self.assertFalse(self.runtime_root.exists())
        return json.loads(self.printed.getvalue()), store

    def test_missing_wrong_version_and_source_import_cannot_pass_identity(self):
        self.verify_identity()
        self.verify_identity(expected="0.66.0", metadata="0.66.0", module_version="0.66.0")
        for arguments in ({"metadata": "9.9.9"}, {"module_version": "9.9.9"},
                          {"metadata": PackageNotFoundError("feast")}, {"location": self.root / "source/feast.py"}):
            with self.subTest(arguments=arguments), self.assertRaises((AssertionError, PackageNotFoundError)):
                self.verify_identity(**arguments)
        with patch.dict("sys.modules", feast=None), self.assertRaises(ModuleNotFoundError):
            exec(compile(self.python_body("FEAST_VERIFY_COMMAND"), "feast-missing-module", "exec"), {})

    def test_both_api_generations_require_historical_and_sqlite_retrieval(self):
        for expected in ("0.10.4", "0.66.0"):
            proof, store = self.execute_runtime(expected=expected)
            self.assertEqual({"installed_version": expected, "historical_rating": 4.5,
                              "online_rating": 4.5, "sqlite_rows": 2}, proof)
            store.materialize.assert_called_once()
            key = "feature_refs" if expected == "0.10.4" else "features"
            self.assertEqual(["driver_ratings:rating"], store.get_historical_features.call_args.kwargs[key])
            self.assertEqual(["driver_ratings:rating"], store.get_online_features.call_args.kwargs[key])

    def test_future_wrong_empty_values_and_runtime_errors_fail_with_cleanup(self):
        for expected in ("0.10.4", "0.66.0"):
            for arguments in ({"historical": (9.0,)}, {"historical": ()}, {"online": (9.0,)},
                              {"online": ()}, {"sqlite_rows": 0}, {"failure": RuntimeError("retrieval failed")}):
                with self.subTest(expected=expected, arguments=arguments):
                    with self.assertRaises((AssertionError, RuntimeError)):
                        self.execute_runtime(expected=expected, **arguments)
                    self.assertFalse(self.runtime_root.exists())
                    self.assertNotIn('"installed_version"', self.printed.getvalue())

    def test_exact_tag_commit_and_cli_version_are_required(self):
        environment = self.stub_commands()
        for tag, changes, valid in (("v0.10.4", {}, True), ("default_branch", {}, False),
                ("v0.10.4", {"TAG_COMMIT": "wrong"}, False), ("v0.10.4", {"HEAD_COMMIT": "wrong"}, False),
                ("v0.10.4", {"CLI_VERSION": "9.9.9"}, False), ("v0.10.4", {"CLI_RC": "23"}, False)):
            with self.subTest(tag=tag, changes=changes):
                result, output = self.run_step("test2", {"steps.install.outputs.resolved_tag": tag}, **{**environment, **changes})
                self.assertEqual(valid, result.returncode == 0, result.stderr)
                self.assertEqual("passed" if valid else "failed", output["status"])
                self.assertGreaterEqual(int(output["duration"]), 0)

    def test_install_clone_and_runtime_failures_cannot_report_success(self):
        environment = self.stub_commands()
        for changes, code in (({"CLONE_RC": "17"}, 17), ({"HEAD_COMMIT": "wrong"}, 1),
                              ({"FEAST_INSTALL_COMMAND": "exit 31"}, 31)):
            result, output = self.run_step("install", **{**environment, **changes})
            self.assertEqual(code, result.returncode)
            self.assertEqual("failed", output["install_status"])
            self.assertNotIn("resolved_tag", output)

    def test_catalog_supported_since_is_separate_from_tested_runtime(self):
        self.assertEqual("0.1.0", self.job["env"]["CATALOG_SUPPORTED_SINCE"])
        self.assertEqual("0.10.4", self.baseline)
        body = re.search(r"^python - <<'PY'\n(.*?)^PY$", self.steps["test2"]["run"], re.M | re.S)[1]
        page = self.root / "feast.md"
        for version, valid in (("0.1.0", True), ("0.10.4", False), ("9.9.9", False)):
            page.write_text(f"---\nsupported_minimum_version:\n  version_number: {version}\n---\n")
            with patch.dict(os.environ, PACKAGE_PAGE=str(page), CATALOG_SUPPORTED_SINCE="0.1.0",
                            SMOKE_VERSION=self.baseline), contextlib.redirect_stdout(io.StringIO()) as output:
                if valid:
                    exec(compile(body, "feast-catalog", "exec"), {})
                    self.assertIn("catalog_supported_since=0.1.0", output.getvalue())
                    self.assertIn("smoke_tested_baseline=0.10.4", output.getvalue())
                else:
                    with self.assertRaises(AssertionError):
                        exec(compile(body, "feast-catalog", "exec"), {})

    def test_each_core_check_records_failure_and_duration(self):
        environment = self.stub_commands()
        values = {"steps.install.outputs.install_status": "success", "steps.install.outputs.resolved_tag": "v0.10.4"}
        for number in range(1, 6):
            with self.subTest(number=number):
                result, output = self.run_step(f"test{number}", values, **{**environment,
                    "FEAST_VERIFY_COMMAND": "exit 23", "FEAST_SMOKE_COMMAND": "exit 23",
                    "CLI_RC": "23", "PYTHON_RC": "23"})
                self.assertEqual(23, result.returncode, result.stderr)
                self.assertEqual("failed", output["status"])
                self.assertGreaterEqual(int(output["duration"]), 0)

    def test_missing_runtime_does_not_emit_pass_or_zero_exit(self):
        for name in ("version", "test1", "test3", "test4", "test5"):
            with self.subTest(name=name):
                result, output = self.run_step(name)
                self.assertNotEqual(0, result.returncode)
                if name == "version":
                    self.assertEqual("unknown", output["version"])
                else:
                    self.assertEqual("failed", output["status"])
                    self.assertIn("duration", output)

    def test_candidate_rejects_wrong_tag_old_version_and_failed_install(self):
        self.steps["probe"] = {"run": self.steps["candidate"]["with"]["limited_cpu_probe"]}
        environment = self.stub_commands()
        for version, tag, valid in (("0.66.0", "v0.66.0", True), ("0.66.0", "v0.10.4", False),
                                   ("0.10.4", "v0.10.4", False), ("0.1.0", "v0.1.0", False)):
            result, _ = self.run_step("probe", **{**environment, "LATEST_VERSION": version,
                "CANDIDATE_TAG": tag, "FEAST_INSTALL_COMMAND": "exit 31"})
            self.assertEqual(31 if valid else 1, result.returncode, result.stderr)
        self.assertEqual("false", self.steps["candidate"]["with"]["defer_on_limited_cpu_probe_failure"])

    def test_candidate_rejects_missing_source_and_failed_smoke_after_install(self):
        self.steps["probe"] = {"run": self.steps["candidate"]["with"]["limited_cpu_probe"]}
        environment = self.stub_commands()
        runtime = self.root / "feast-next-venv/bin"
        runtime.mkdir(parents=True)
        (runtime / "activate").write_text(":\n")
        environment.update(LATEST_VERSION="0.66.0", CANDIDATE_TAG="v0.66.0",
                           FEAST_INSTALL_COMMAND="true", FEAST_SMOKE_COMMAND="exit 37")
        for changes, expected in (({}, 37), ({"GIT_RC": "19"}, 19),
                                  ({"HEAD_COMMIT": "", "TAG_COMMIT": ""}, 1),
                                  ({"TAG_COMMIT": "wrong"}, 1)):
            result, _ = self.run_step("probe", **{**environment, **changes})
            self.assertEqual(expected, result.returncode, result.stderr)

    def regression_values(self, candidate=None, **changes):
        values = self.statuses()
        values.update({"steps.candidate.outcome": "success"})
        values.update({f"steps.candidate.outputs.{key}": value for key, value in (candidate or {}).items()})
        values.update(changes)
        return values

    def assert_policy_and_summary(self, output, core, outcome):
        self.assertIn((output["decision"], output["status"]),
                      audit._step_literal_pairs(WORKFLOW.parents[2], self.steps["test6"]))
        details = [{"name": f"Test {index}", "status": status}
                   for index, status in enumerate(core + [output["status"]], 1)]
        details[-1]["decision"] = output["decision"]
        values = self.statuses()
        for index, status in enumerate(core, 1):
            values[f"steps.test{index}.outputs.status"] = status
            values[f"steps.test{index}.outcome"] = "success" if status == "passed" else "failure"
        values.update({f"steps.test6.outputs.{key}": value for key, value in output.items()})
        values["steps.test6.outcome"] = outcome
        result, counts = self.run_step("summary", values)
        expected = POLICY.validate_six_test_result(details=details, decision=output["decision"],
            **{key: int(counts[key]) for key in ("passed", "failed", "skipped", "core_failed")})
        self.assertEqual(expected, counts["overall_status"])
        self.assertEqual(expected == "success", result.returncode == 0)

    def test_actual_steps_emit_auditable_status_duration_and_decision_pairs(self):
        self.assertEqual("${{ steps.test6.outputs.decision || 'not_configured' }}",
                         self.job["outputs"]["regression_decision"])
        for number in range(1, 7):
            for output in ("status", "duration"):
                with self.subTest(number=number, output=output):
                    self.assertTrue(audit._step_emits_output(
                        WORKFLOW.parents[2], self.steps[f"test{number}"], output))
        pairs = set(audit._step_literal_pairs(WORKFLOW.parents[2], self.steps["test6"]))
        self.assertEqual({("limited_cpu_smoke_validated", "passed"),
                          ("limited_cpu_smoke_failed", "failed"),
                          ("next_install_failed", "failed"),
                          ("next_lookup_failed", "failed"),
                          ("next_regression_failed", "failed"),
                          ("baseline_failed", "skipped"),
                          ("no_newer_stable_available", "skipped")}, pairs)
        self.assertEqual({decision for decision, _ in pairs},
                         set(audit._step_literal_outputs(WORKFLOW.parents[2], self.steps["test6"], "decision")))
        for decision, status in pairs:
            with self.subTest(decision=decision):
                self.assertEqual(status, audit._expected_raw_status(POLICY.decision_group(decision)))

    def test_actual_test6_decision_records_match_audited_pairs_and_policy(self):
        binary = self.root / "bin"
        binary.mkdir()
        (binary / "python").symlink_to(sys.executable)
        candidate = dict(latest_version="0.66.0", next_installed_version="0.66.0", duration="3",
                         regression_result="fixture", comparison="fixture")
        for status, decision, expected_status, expected_decision in (
                ("passed", "limited_cpu_smoke_validated", "passed", "limited_cpu_smoke_validated"),
                ("failed", "limited_cpu_smoke_failed", "failed", "limited_cpu_smoke_failed"),
                ("failed", "next_install_failed", "failed", "next_install_failed"),
                ("skipped", "metadata_review_required", "failed", "next_lookup_failed"),
                ("skipped", "no_newer_stable_available", "skipped", "no_newer_stable_available"),
                ("passed", "unapproved", "failed", "next_regression_failed")):
            with self.subTest(decision=decision):
                values = self.regression_values({**candidate, "status": status, "decision": decision})
                result, output = self.run_step("test6", values, PATH=str(binary) + os.pathsep + os.environ["PATH"])
                self.assertEqual((expected_decision, expected_status), (output["decision"], output["status"]))
                self.assertEqual(expected_status != "failed", result.returncode == 0, result.stderr)
                self.assertEqual("3", output["duration"])
                self.assert_policy_and_summary(output, ["passed"] * 5,
                                               "success" if result.returncode == 0 else "failure")

    def test_test6_python_failure_preserves_literal_failed_defaults(self):
        binary = self.root / "bin"
        binary.mkdir()
        (binary / "python").symlink_to(sys.executable)
        for changes in ({"GITHUB_WORKSPACE": str(self.root)}, {"CORE_RESULTS": "passed:success"}):
            with self.subTest(changes=changes):
                result, output = self.run_step("test6", self.regression_values(),
                    PATH=str(binary) + os.pathsep + os.environ["PATH"], **changes)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual({"status": "failed", "duration": "0", "decision": "next_regression_failed"}, output)
                self.assert_policy_and_summary(output, ["passed"] * 5, "failure")

    def test_actual_composite_success_and_failure_decisions_match_policy(self):
        action = yaml.safe_load((WORKFLOW.parents[1] / "actions/generic-source-regression-check/action.yml").read_text())
        body = action["runs"]["steps"][0]
        self.steps["composite"] = body
        inputs = {f"inputs.{key}": str(value.get("default", "")) for key, value in action["inputs"].items()}
        inputs.update({"inputs.baseline_version": self.baseline, "inputs.github_repo": "feast-dev/feast",
                       "inputs.next_version_override": "0.66.0", "inputs.candidate_tag_override": "v0.66.0",
                       "inputs.limited_cpu_probe": self.steps["candidate"]["with"]["limited_cpu_probe"],
                       "inputs.limited_cpu_description": self.steps["candidate"]["with"]["limited_cpu_description"]})
        environment = self.stub_commands()
        runtime = self.root / "feast-next-venv/bin"
        runtime.mkdir(parents=True)
        (runtime / "activate").write_text(":\n")
        for smoke, status, decision in (("true", "passed", "limited_cpu_smoke_validated"),
                                       ("exit 37", "failed", "limited_cpu_smoke_failed")):
            result, emitted = self.run_step("composite", inputs, **{**environment,
                "FEAST_INSTALL_COMMAND": "true", "FEAST_SMOKE_COMMAND": smoke})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual((status, decision), (emitted["status"], emitted["decision"]))
            approved = POLICY.PASSED_REGRESSION_DECISIONS if status == "passed" else POLICY.FAILED_REGRESSION_DECISIONS
            self.assertIn(emitted["decision"], approved)
            self.assertNotIn(emitted["decision"], POLICY.BASELINE_REGRESSION_DECISIONS)
            result, output = self.run_step("test6", self.regression_values(emitted),
                                            PATH=str(self.root / "bin") + os.pathsep + os.environ["PATH"])
            self.assertEqual((status, decision), (output["status"], output["decision"]))
            self.assertEqual(status == "passed", result.returncode == 0)
            self.assert_policy_and_summary(output, ["passed"] * 5, "success" if result.returncode == 0 else "failure")

    def test_baseline_failure_emits_approved_skip_and_still_fails_run(self):
        binary = self.root / "bin"
        binary.mkdir()
        (binary / "python").symlink_to(sys.executable)
        values = self.regression_values(**{"steps.test5.outputs.status": "failed", "steps.test5.outcome": "failure"})
        result, output = self.run_step("test6", values, PATH=str(binary) + os.pathsep + os.environ["PATH"])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("skipped", "baseline_failed", "not_installed"),
                         tuple(output[key] for key in ("status", "decision", "next_installed_version")))
        self.assertIn(output["decision"], POLICY.BASELINE_REGRESSION_DECISIONS)
        self.assert_policy_and_summary(output, ["passed"] * 4 + ["failed"], "success")
        for index in range(1, 6):
            self.assertIn(f"steps.test{index}.outcome == 'success'", self.steps["candidate"]["if"])

    def test_incoherent_candidate_outputs_fail_with_approved_decision(self):
        binary = self.root / "bin"
        binary.mkdir()
        (binary / "python").symlink_to(sys.executable)
        candidate = dict(status="passed", decision="limited_cpu_smoke_validated", latest_version="0.66.0",
                         next_installed_version="0.66.0", duration="3", regression_result="fixture", comparison="fixture")
        for changes in ({"decision": "unapproved"}, {"status": "failed"}, {"next_installed_version": "0.1.0"},
                        {"latest_version": ""}, {"next_installed_version": ""},
                        {"duration": ""}, {"status": "skipped", "decision": "runtime_validation_not_automated"}):
            result, output = self.run_step("test6", self.regression_values({**candidate, **changes}),
                                            PATH=str(binary) + os.pathsep + os.environ["PATH"])
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", output["status"])
            self.assertIn(output["decision"], POLICY.FAILED_REGRESSION_DECISIONS)
            self.assert_policy_and_summary(output, ["passed"] * 5, "failure")

    def test_original_import_error_is_a_failed_core_check_not_a_skip(self):
        result, output = self.run_step("summary", {**self.statuses(),
            "steps.test5.outputs.status": "", "steps.test5.outcome": "failure"})
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("5", "1", "0", "1", "failure"), tuple(output[key]
            for key in ("passed", "failed", "skipped", "core_failed", "overall_status")))

    def test_failed_and_missing_outcomes_cannot_be_overridden(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", "skipped", ""):
                result, output = self.run_step("summary", {**self.statuses(), f"steps.test{number}.outcome": outcome})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", output["failed"])
                self.assertEqual("1" if number <= 5 else "0", output["core_failed"])

    def test_genuine_pass_and_only_proven_no_candidate_keep_exact_counts(self):
        values = {**self.statuses(), **{f"steps.test{i}.outputs.duration": str(i) for i in range(1, 7)}}
        result, output = self.run_step("summary", values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("6", "0", "0", "21"), tuple(output[key] for key in ("passed", "failed", "skipped", "duration")))
        for decision, valid in (("no_newer_stable_available", True), ("runtime_validation_not_automated", False), ("", False)):
            result, output = self.run_step("summary", {**values, "steps.test6.outputs.status": "skipped",
                                                      "steps.test6.outputs.decision": decision})
            self.assertEqual(valid, result.returncode == 0)
            self.assertEqual("1" if valid else "0", output["skipped"])


if __name__ == "__main__":
    unittest.main()
