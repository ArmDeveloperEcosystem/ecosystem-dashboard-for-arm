"""Execute BenchmarkSQL workflow checks with local Git and offline build fixtures."""

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
import promote_package_results as promoter


class BenchmarkSqlSmokeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="benchmarksql-workflow-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "tmp").mkdir()
        self.workflow = yaml.safe_load((ROOT / ".github/workflows/test-benchmarksql.yml").read_text())
        self.job = self.workflow["jobs"]["test-benchmarksql"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.git = os.environ.get("GIT_TEST_EXECUTABLE", shutil.which("git"))
        self.env = {**os.environ, **self.job["env"], "PYTHONDONTWRITEBYTECODE": "1",
                    "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "REAL_GIT": self.git, "CALLS": str(self.root / "calls"),
                    "GITHUB_OUTPUT": str(self.root / "outputs"),
                    "GIT_AUTHOR_NAME": "Offline Fixture", "GIT_COMMITTER_NAME": "Offline Fixture",
                    "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "pom.xml").write_text(
            '<project xmlns="http://maven.apache.org/POM/4.0.0"><groupId>com.github.pgsql-io</groupId>'
            '<artifactId>benchmarksql</artifactId><version>6.0.0</version></project>')
        script = self.source / "src/main/resources/runBenchmark.sh"
        script.parent.mkdir(parents=True)
        script.write_text('#!/bin/sh\necho "${USAGE_TEXT:-usage: runBenchmark.sh PROPS_FILE}"\nexit "${USAGE_EXIT:-2}"\n')
        script.chmod(0o755)
        self.git_run("init", "-q")
        self.git_run("add", ".")
        self.git_run("-c", "commit.gpgsign=false", "commit", "-qm", "Offline fixture, not upstream source")
        self.git_run("-c", "tag.gpgsign=false", "tag", "-a", "REL6_0_RC2", "-m", "Offline fixture")
        self.git_run("-c", "tag.gpgsign=false", "tag", "-a", "REL5_1", "-m", "Offline older fixture")
        self.env.update(BENCHMARKSQL_SOURCE_URL=str(self.source),
                        BENCHMARKSQL_TAG_OBJECT=self.git_run("rev-parse", "REL6_0_RC2"),
                        BENCHMARKSQL_COMMIT=self.git_run("rev-parse", "HEAD"),
                        BENCHMARKSQL_TREE=self.git_run("rev-parse", "HEAD^{tree}"))
        self.stub("git", r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as output:
    output.write(json.dumps(["git"] + args) + "\n")
if args[0] == "ls-remote" and "INVENTORY" in os.environ:
    if os.environ["INVENTORY"] == "error":
        sys.exit(128)
    print(os.environ["INVENTORY"])
    sys.exit(0)
os.execv(os.environ["REAL_GIT"], [os.environ["REAL_GIT"]] + args)
''')
        self.stub("mvn", r'''
import json, os, shutil, sys
from pathlib import Path
assert sys.argv[1:] == ["-B", "package"]
with open(os.environ["CALLS"], "a") as output:
    output.write(json.dumps(["mvn"] + sys.argv[1:]) + "\n")
if os.environ.get("BUILD_FAIL"):
    sys.exit(9)
Path("target/run").mkdir(parents=True)
Path("target/BenchmarkSQL.jar").write_bytes(b"OFFLINE BUILD FIXTURE, NOT A JAVA ARTIFACT")
shutil.copy("src/main/resources/runBenchmark.sh", "target/run/runBenchmark.sh")
''')
        self.stub("javac", r'''
import json, os, sys
from pathlib import Path
with open(os.environ["CALLS"], "a") as output:
    output.write(json.dumps(["javac"] + sys.argv[1:]) + "\n")
assert "benchmarksql/target/BenchmarkSQL.jar:benchmarksql/target/lib/*" in sys.argv
source = Path(sys.argv[-1]).read_text()
for required in ("new jTPCCRandom()", "getCodeSource()", 'getCLast(123).equals("OUGHTABLEPRI")',
                 "nextInt(1, 10)", "nextLong(1, 100)", "nextDouble(0.0, 1.0)", "getAString(8, 16)",
                 "getNString(8, 8)", "getState()", "getItemID()", "getCustomerID()", "throw new AssertionError"):
    assert required in source, required
sys.exit(7 if os.environ.get("COMPILE_FAIL") else 0)
''')
        self.stub("java", r'''
import json, os, sys
with open(os.environ["CALLS"], "a") as output:
    output.write(json.dumps(["java"] + sys.argv[1:]) + "\n")
if sys.argv[1:] == ["-version"]:
    print('openjdk version "17 offline fixture"')
else:
    assert sys.argv[-2:] == ["BenchmarkSqlDataSmoke", "benchmarksql/target/BenchmarkSQL.jar"]
sys.exit(8 if os.environ.get("JAVA_FAIL") else 0)
''')
        self.stub("timeout", r'''
import os, sys
assert sys.argv[1:4] == ["--signal=TERM", "--kill-after=5s", "30s"]
os.execvp(sys.argv[4], sys.argv[4:])
''')
        self.stub("uname", 'import os\nprint(os.environ.get("FIXTURE_ARCH", "aarch64"))\n')
        self.values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)}
        self.values.update({f"steps.test{i}.outcome": "success" for i in range(1, 7)})
        self.values.update({"steps.test6.outputs.status": "skipped",
                            "steps.test6.outputs.decision": "no_newer_stable_available",
                            "steps.test6.outputs.regression_result": "Verified public tag inventory",
                            "steps.test6.outputs.comparison": "No candidate was installed or executed."})

    def git_run(self, *args):
        return subprocess.check_output([self.git, *args], cwd=self.source, env=self.env,
                                       text=True, stderr=subprocess.STDOUT).strip()

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def render(self, source, values):
        def expression(match):
            terms = match[1].split("||")
            return values.get(terms[0].strip()) or (terms[1].strip().strip("'") if len(terms) > 1 else "")
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)

    def run_step(self, name, values=None, **environment):
        step = self.steps[name]
        bindings = {**self.values, **(values or {})}
        env = {**self.env, **{k: self.render(str(v), bindings) for k, v in step.get("env", {}).items()}, **environment}
        output = Path(env["GITHUB_OUTPUT"])
        output.write_text("")
        script = self.render(step["run"], bindings).replace("/tmp/benchmarksql", str(self.root / "tmp/benchmarksql"))
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
                                env=env, text=True, capture_output=True, timeout=30)
        fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, fields

    def calls(self):
        path = self.root / "calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def install(self):
        result, fields = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("success", fields["install_status"])

    def test_historical_source_identity_and_workflow_permissions(self):
        expected = {"BENCHMARKSQL_BASELINE_VERSION": "REL6_0_RC2",
                    "BENCHMARKSQL_SOURCE_URL": "https://github.com/wieck/benchmarksql.git",
                    "BENCHMARKSQL_TAG_OBJECT": "dfaeb8482add83b8fa6d61b2cad9f8906c05315c",
                    "BENCHMARKSQL_COMMIT": "98f5cb4b446f4296ca5e85ad27303482a6bbd624",
                    "BENCHMARKSQL_TREE": "3841f1cc53553613e5c80386965d645f97c9a9c4"}
        for key, value in expected.items():
            self.assertEqual(value, self.job["env"][key])
        self.assertEqual({"contents": "read"}, self.workflow["permissions"])
        self.assertEqual({"workflow_dispatch", "workflow_call"}, set(self.workflow[True]))
        actions = [s for s in self.job["steps"] if "uses" in s]
        self.assertEqual(1, len(actions))
        self.assertFalse(actions[0]["with"]["persist-credentials"])
        self.assertNotIn("-DskipTests", self.steps["install"]["run"])

    def test_real_git_fetch_observed_version_and_five_baseline_checks(self):
        self.install()
        result, fields = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("REL6_0_RC2", fields["version"])
        for i in range(1, 6):
            result, fields = self.run_step(f"test{i}")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("passed", fields["status"])
        calls = self.calls()
        self.assertTrue(any(c[0] == "javac" for c in calls))
        self.assertTrue(any(c[0] == "java" and "BenchmarkSqlDataSmoke" in c for c in calls))

    def test_wrong_tag_commit_tree_and_missing_source_prevent_build(self):
        cases = [{key: "0" * 40} for key in ("BENCHMARKSQL_TAG_OBJECT", "BENCHMARKSQL_COMMIT", "BENCHMARKSQL_TREE")]
        cases.append({"BENCHMARKSQL_SOURCE_URL": str(self.root / "missing-source")})
        for environment in cases:
            with self.subTest(environment=environment):
                shutil.rmtree(self.root / "benchmarksql", ignore_errors=True)
                result, fields = self.run_step("install", **environment)
                self.assertNotEqual(0, result.returncode)
                self.assertNotEqual("success", fields.get("install_status"))
        self.assertFalse(any(c[0] == "mvn" for c in self.calls()))

    def test_build_failure_and_wrong_observed_version_are_not_accepted(self):
        result, fields = self.run_step("install", BUILD_FAIL="1")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", fields["install_status"])
        for env in ({"BENCHMARKSQL_COMMIT": "0" * 40}, {"BENCHMARKSQL_TREE": "0" * 40},
                    {"BENCHMARKSQL_BASELINE_VERSION": "REL5_1"}):
            result, fields = self.run_step("version", **env)
            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("version", fields)
        pom = self.root / "benchmarksql/pom.xml"
        pom.write_text(pom.read_text().replace("6.0.0", "5.1.0"))
        result, fields = self.run_step("version")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("version", fields)

    def test_launcher_java_compile_runtime_and_architecture_failures_propagate(self):
        self.install()
        for env in ({"USAGE_TEXT": "unrelated"}, {"USAGE_EXIT": "0"}, {"COMPILE_FAIL": "1"}, {"JAVA_FAIL": "1"}):
            with self.subTest(env=env):
                result, fields = self.run_step("test5", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertNotEqual("passed", fields.get("status"))
        (self.root / "benchmarksql/target/BenchmarkSQL.jar").unlink()
        result, fields = self.run_step("test5")
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("passed", fields.get("status"))
        result, fields = self.run_step("test4", FIXTURE_ARCH="x86_64")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", fields["status"])

    def test_live_tag_inventory_is_a_truthful_skip_not_candidate_execution(self):
        result, fields = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("no_newer_stable_available", fields["decision"])
        self.assertEqual("skipped", fields["status"])
        self.assertEqual("not_installed", fields["next_installed_version"])
        self.assertIn("Checked 2 public maintainer tags", fields["regression_result"])
        self.assertIn("no candidate was installed or executed", fields["comparison"])

    def test_lookup_errors_malformed_missing_duplicate_and_moved_tags_fail(self):
        tag = self.env["BENCHMARKSQL_TAG_OBJECT"] + "\trefs/tags/REL6_0_RC2"
        for inventory in ("error", "", "garbage", tag + "\n" + tag,
                          "0" * 40 + "\trefs/tags/REL6_0_RC2", "0" * 40 + "\trefs/tags/unrecognized"):
            with self.subTest(inventory=inventory):
                result, fields = self.run_step("test6", INVENTORY=inventory)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", fields["status"])
                self.assertEqual("next_regression_failed", fields["decision"])

    def test_newer_release_or_rc_requires_real_candidate_validation(self):
        for tag in ("REL6_0", "REL6_0_RC3", "REL6_1", "REL7_0"):
            with self.subTest(tag=tag):
                self.git_run("tag", tag)
                result, fields = self.run_step("test6")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(tag, fields["latest_version"])
                self.assertIn("neither was completed", fields["regression_result"])
                self.git_run("tag", "-d", tag)

    def test_summary_accounts_all_six_checks_and_rejects_unmeasured_green(self):
        result, fields = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1"), tuple(fields[k] for k in ("passed", "failed", "skipped")))
        cases = [{"steps.test6.outputs.status": status, "steps.test6.outputs.decision": decision}
                 for status, decision in (("", ""), ("passed", "next_install_validated"),
                     ("skipped", "metadata_review_required"), ("skipped", "runtime_validation_not_automated"),
                     ("skipped", "not_applicable_package_manager"), ("failed", "next_regression_failed"))]
        cases += [{"steps.test6.outcome": value} for value in ("failure", "skipped", "")]
        for values in cases:
            with self.subTest(values=values):
                result, fields = self.run_step("summary", values)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("5", "1", "0"), tuple(fields[k] for k in ("passed", "failed", "skipped")))
                self.assertEqual("next_regression_failed", fields["regression_decision"])

    def test_baseline_failure_and_missing_outputs_never_become_skips_or_green(self):
        for i in range(1, 6):
            self.assertIn(f"steps.test{i}.outcome == 'success'", self.steps["test6"]["if"])
            self.assertIn(f"steps.test{i}.outputs.status == 'passed'", self.steps["test6"]["if"])
            for key, value in (("outputs.status", ""), ("outputs.status", "failed"), ("outcome", "failure")):
                result, fields = self.run_step("summary", {f"steps.test{i}.{key}": value})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("4", "1", "1", "1"), tuple(fields[k] for k in ("passed", "failed", "skipped", "core_failed")))
                self.assertEqual("baseline_failed", fields["regression_decision"])

    def collect(self, summary, regression, conclusions):
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        bindings = {**self.values, **{f"steps.summary.outputs.{k}": v for k, v in summary.items()},
                    **{f"steps.test6.outputs.{k}": v for k, v in regression.items()},
                    "steps.version.outputs.version": "REL6_0_RC2", "steps.metadata.outputs.package_slug": "benchmarksql",
                    "steps.metadata.outputs.dashboard_link": "/linux/opensource_packages/benchmarksql",
                    "steps.metadata.outputs.timestamp": "2026-10-28T15:32:00Z",
                    "github.run_id": "123", "github.run_attempt": "1", "github.job": "test-benchmarksql"}
        outputs = {k: self.render(str(v), bindings) for k, v in self.job["outputs"].items()}
        job = {"id": 456, "name": "test-benchmarksql / test-benchmarksql", "conclusion": summary["overall_status"],
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "steps": [{"name": self.steps[f"test{i}"]["name"], "number": i, "conclusion": state}
                         for i, state in enumerate(conclusions, 1)]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(SCRIPTS)
            result = subprocess.run([sys.executable, "-B", "-c", source], cwd=root,
                env={**self.env, "NEEDS_JSON": json.dumps({"test-benchmarksql": {"result": summary["overall_status"], "outputs": outputs}}),
                     "RUN_JOBS_JSON": json.dumps({"jobs": [job]}), "BATCH_NUMBER": "7", "BATCH_TITLE": "Batch 7",
                     "GH_TOKEN": "", "GITHUB_TOKEN": "", "GITHUB_SERVER_URL": "https://github.com",
                     "GITHUB_STEP_SUMMARY": str(root / "summary"), "GITHUB_API_URL": "https://api.github.com",
                     "GITHUB_REPOSITORY": "example/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"},
                capture_output=True, text=True, timeout=30)
            path = root / "test-results/benchmarksql-test-results/benchmarksql.json"
            return result, json.loads(path.read_text()) if path.exists() else None, job

    def test_active_collector_and_strict_publisher_retain_real_skip_and_failure(self):
        for failed in (False, True):
            _, regression = self.run_step("test6", **({"INVENTORY": "error"} if failed else {}))
            values = {f"steps.test6.outputs.{k}": v for k, v in regression.items()}
            values["steps.test6.outcome"] = "failure" if failed else "success"
            result, summary = self.run_step("summary", values)
            self.assertEqual(failed, result.returncode != 0)
            collected, payload, job = self.collect(summary, regression, ["success"] * 5 + ["failure" if failed else "success"])
            self.assertEqual(0, collected.returncode, collected.stdout + collected.stderr)
            self.assertEqual("failure" if failed else "success", policy.validate_publishable_result(payload))
            self.assertEqual((5, 1, 0) if failed else (5, 0, 1), tuple(payload["tests"][k] for k in ("passed", "failed", "skipped")))
            detail = payload["tests"]["details"][5]
            self.assertEqual(summary["regression_result"], detail["regression_result"])
            self.assertEqual(regression["comparison"], detail["comparison"])
            registration = {"batch_title": "Batch 7", "workflow_path": ".github/workflows/test-all-packages-batch7.yml",
                            "run_id": "123", "run_attempt": "1", "job_name": job["name"], "job_url": job["html_url"],
                            "job_conclusion": job["conclusion"], "job_started_at": "2026-10-28T15:31:00Z",
                            "job_completed_at": "2026-10-28T15:33:00Z", "resolution_status": "central_exact"}
            self.assertEqual("failure" if failed else "success", promoter.validate_persisted_result(payload,
                expected_slug="benchmarksql", expected_repository="example/project", expected_registration=registration,
                publication_role="candidate", validation_policy="strict", allow_legacy_missing_decision=False))


if __name__ == "__main__":
    unittest.main()
