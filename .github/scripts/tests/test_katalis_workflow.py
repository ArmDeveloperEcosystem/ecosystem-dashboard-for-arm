"""Execute Katalis's actual YAML shell logic, with tool doubles for unit tests.

Native proof: python3 .github/scripts/tests/test_katalis_workflow.py --native-run DIR
This runs the checked-out YAML blocks on an authorized disposable Arm64 host.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_result_policy import validate_six_test_result


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-katalis.yml"
FIXTURE = ROOT / ".github/scripts/tests/fixtures/katalis_smoke.go"
JOB = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-katalis"]
STEPS = {step["id"]: step for step in JOB["steps"] if "id" in step}
LIBRARY = STEPS["prepare"]["run"].split("<<'KATALIS_LIB'\n", 1)[1].split("\nKATALIS_LIB\n", 1)[0]


def read_outputs(path):
    if not path.exists():
        return {}
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def resolve(value, steps):
    value = str(value)
    match = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", value)
    if not match:
        return value
    for term in match[1].split(" || "):
        term = term.strip()
        if term.startswith("'") and term.endswith("'"):
            return term[1:-1]
        if term.startswith("github."):
            return {"github.job": "test-katalis", "github.run_id": "native-pr951", "github.run_attempt": "1"}[term]
        field = re.fullmatch(r"steps\.([a-z0-9_]+)\.(?:outputs\.([a-z_0-9]+)|(outcome))", term)
        if field is None:
            raise ValueError(f"Unsupported expression: {term}")
        record = steps.get(field[1], {})
        result = record.get("outputs", {}).get(field[2], "") if field[2] else record.get("outcome", "")
        if result:
            return str(result)
    return ""


def render(script, steps):
    return re.sub(r"\$\{\{.*?\}\}", lambda match: resolve(match[0], steps), script)


# All tool doubles are limited to unit tests. --native-run never creates or uses them.
TOOLS = r'''
import os, pathlib, re, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ['KATALIS_ROOT'])
failure = os.environ.get('MOCK_FAILURE', '')
with (root / 'calls.jsonl').open('a') as f:
    f.write(__import__('json').dumps([name, args]) + '\n')
if name == 'sudo':
    os.execvp(args[1], args[1:])
if name == 'timeout':
    while args[0].startswith('--'):
        args.pop(0)
    args.pop(0)
    os.execvp(args[0], args)
if name == 'uname':
    print('x86_64' if failure == 'host_arch' else 'aarch64')
elif name == 'git':
    src = pathlib.Path(args[args.index('-C') + 1])
    component = src.name
    lane = 'BASELINE' if src.parent.name == 'baseline' else 'NEXT'
    version = os.environ['BASELINE_VERSION' if lane == 'BASELINE' else component.upper() + '_NEXT_VERSION']
    sha = os.environ[component.upper() + '_' + lane + '_SHA']
    if 'fetch' in args and failure == 'missing_tag':
        sys.exit(128)
    if 'rev-parse' in args:
        print('0' * 40 if failure == 'source' else sha)
    elif 'describe' in args:
        print('v9.9.9' if failure == 'tag' else 'v' + version)
    elif 'status' in args and failure == 'dirty':
        print(' M go.mod')
elif name == 'file':
    binary = pathlib.Path(args[-1])
    if not binary.is_file():
        print('cannot open: No such file')
    else:
        print(str(binary) + ': ELF 64-bit LSB executable, ' + ('x86-64' if failure == 'artifact_arch' else 'ARM aarch64'))
elif name == 'docker':
    if args[:2] == ['container', 'inspect']:
        sys.exit(0 if (root / 'runtime-live').exists() else 1)
    if args[:2] == ['rm', '-f']:
        (root / 'runtime-live').unlink()
        sys.exit(0)
    if '/work/bin/katalis-smoke' in args:
        (root / 'runtime-live').touch()
        if failure in ('api_response', 'operator_reconcile', 'process_exit', 'functional_timeout'):
            sys.exit(124 if failure == 'functional_timeout' else 43)
        (root / 'runtime-live').unlink()
        sys.exit(0)
    command = args[-1]
    cwd = pathlib.Path(args[args.index('-w') + 1])
    lane, component = cwd.parts[-2:]
    key = component.upper() + ('_BASELINE_SHA' if lane == 'baseline' else '_NEXT_SHA')
    if 'go mod download' in command and failure in ('download', 'checksum'):
        sys.exit(31)
    if 'go build' in command:
        if failure == 'build':
            sys.exit(32)
        destination = re.search(r'-o (\S+)', command)[1]
        binary = root / destination.replace('/work/', 'work/', 1)
        binary.parent.mkdir(parents=True, exist_ok=True)
        if binary.name == 'api':
            binary.write_text("#!/bin/sh\necho 'required key CONTROLLER_NAMESPACE missing value'\nexit 1\n")
        elif binary.name == 'operator':
            binary.write_text("#!/bin/sh\nprintf '%s\\n' '-health-probe-bind-address' '-metrics-bind-address'\n")
        else:
            binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o755)
    if 'go version -m' in command:
        suffix = '/cmd/app' if component == 'api' else '/cmd'
        print('path\tgithub.com/neonephos-katalis/opg-ewbi-' + component + suffix)
        for item in ['vcs.revision=' + ('0' * 40 if failure == 'binary_revision' else os.environ[key]),
                     'vcs.modified=' + ('true' if failure == 'binary_dirty' else 'false'),
                     'GOOS=linux', 'GOARCH=' + ('amd64' if failure == 'go_arch' else 'arm64'), 'CGO_ENABLED=0']:
            print('build\t' + item)
'''


class KatalisWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="katalis-shell-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "tools"
        self.bin.mkdir()
        self.env = {**os.environ, **JOB["env"], "KATALIS_ROOT": str(self.root),
                    "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "GITHUB_OUTPUT": str(self.root / "output"),
                    "GITHUB_STEP_SUMMARY": str(self.root / "summary")}
        self.env.update({f"BASELINE_STATUS_{i}": "passed" for i in range(1, 6)})
        self.env.update({f"BASELINE_OUTCOME_{i}": "success" for i in range(1, 6)})
        for tool in ("sudo", "timeout", "docker", "git", "file", "uname"):
            path = self.bin / tool
            path.write_text(f"#!{sys.executable}\n" + TOOLS)
            path.chmod(0o755)
        (self.root / "katalis-lib.sh").write_text(LIBRARY)
        (self.root / "runtime").mkdir()
        for lane in ("baseline", "candidate"):
            for component in ("operator", "api"):
                (self.root / "work" / lane / component).mkdir(parents=True)
                binary = self.root / "work/bin" / lane / component
                binary.parent.mkdir(parents=True, exist_ok=True)
                if component == "operator":
                    binary.write_text("#!/bin/sh\nprintf '%s\\n' '-health-probe-bind-address' '-metrics-bind-address'\n")
                else:
                    binary.write_text("#!/bin/sh\necho 'required key CONTROLLER_NAMESPACE missing value'\nexit 1\n")
                binary.chmod(0o755)

    def shell(self, script, **env):
        output = self.root / "output"
        output.write_text("")
        facts = {f"test{i}": {"outcome": env.get(f"OUTCOME_{i}", ""), "outputs": {
                    "status": env.get(f"STATUS_{i}", ""), "duration": env.get(f"DURATION_{i}", "0")}}
                 for i in range(1, 7)}
        facts["test6"]["outputs"]["decision"] = env.get("REGRESSION_DECISION", "")
        result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", render(script, facts)],
                                env={**self.env, **env}, capture_output=True, text=True, timeout=30)
        return result, read_outputs(output)

    def step(self, name, **env):
        return self.shell(STEPS[name]["run"], **env)

    def test_single_native_job_contract_and_pins(self):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        self.assertEqual(list(workflow["jobs"]), ["test-katalis"])
        self.assertEqual(JOB["runs-on"], "ubuntu-24.04-arm")
        self.assertNotIn("container", JOB)
        self.assertNotIn("services", JOB)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        actions = [s["uses"] for s in JOB["steps"] if "uses" in s]
        self.assertEqual(actions, ["actions/checkout@11d5960a326750d5838078e36cf38b85af677262"])
        trigger = workflow.get("on", workflow.get(True))
        self.assertEqual(set(trigger["workflow_call"]["outputs"]), set(JOB["outputs"]))
        self.assertEqual(JOB["outputs"]["contract_version"], "2.0")
        self.assertEqual(JOB["outputs"]["regression_policy"], "applicable")
        self.assertNotIn("not_applicable_package_manager", WORKFLOW.read_text())

    def test_every_shell_block_parses(self):
        for step in JOB["steps"]:
            if "run" in step:
                with self.subTest(step=step["name"]):
                    result = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_active_auditor_sees_all_result_producers_and_summary_inputs(self):
        import package_observation_migration_audit as audit
        for i in range(1, 7):
            self.assertTrue(audit._step_emits_output(ROOT, STEPS[f"test{i}"], "status"))
            self.assertTrue(audit._step_emits_output(ROOT, STEPS[f"test{i}"], "duration"))
        source = audit._step_source(ROOT, STEPS["summary"])
        self.assertTrue(audit._shell_code_contains(source, "steps.test6.outputs.status"))
        for i in range(1, 7):
            self.assertTrue(audit._shell_code_contains(source, f"steps.test{i}.outputs.duration"))

    def test_missing_preparation_still_emits_each_baseline_failure(self):
        (self.root / "katalis-lib.sh").unlink()
        for i in range(1, 6):
            result, outputs = self.step(f"test{i}")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs["status"], "failed")
            self.assertGreaterEqual(int(outputs["duration"]), 0)

    def test_install_and_version_success(self):
        result, outputs = self.step("install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["install_status"], "success")
        result, outputs = self.step("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["version"], "0.0.2")
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        runs = [args for name, args in calls if name == "docker"]
        builds = [args for args in runs if "go build" in args[-1]]
        self.assertEqual(len(builds), 3)
        self.assertTrue(all(args[args.index("--network") + 1] == "none" for args in builds))
        self.assertTrue(all("-buildvcs=true" in args[-1] for args in builds[:2]))
        self.assertTrue(all("GOWORK=/work/baseline/go.work" in args for args in runs))

    def test_install_errors_cannot_emit_success(self):
        for failure in ("missing_tag", "source", "download", "checksum", "build", "dirty"):
            with self.subTest(failure=failure):
                result, outputs = self.step("install", MOCK_FAILURE=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(outputs.get("install_status"), "success")

    def test_binary_or_install_absence_fails_test1(self):
        for status in ("failed", "", "success"):
            if status == "success":
                (self.root / "work/bin/baseline/api").unlink()
            result, outputs = self.step("test1", INSTALL_STATUS=status)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs["status"], "failed")
            self.assertGreaterEqual(int(outputs["duration"]), 0)

    def test_real_detected_version_rejects_wrong_source_tag_or_binary(self):
        for failure in ("source", "tag", "dirty", "binary_revision", "binary_dirty", "go_arch", "artifact_arch"):
            with self.subTest(failure=failure):
                result, outputs = self.step("version", MOCK_FAILURE=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("version", outputs)
                result, outputs = self.step("test2", DETECTED_VERSION="0.0.2", MOCK_FAILURE=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["status"], "failed")
        result, outputs = self.step("test2", DETECTED_VERSION="9.9.9")
        self.assertEqual(outputs["status"], "failed")

    def test_interfaces_require_both_real_expected_behaviors(self):
        result, outputs = self.step("test3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["status"], "passed")
        for component in ("operator", "api"):
            binary = self.root / "work/bin/baseline" / component
            original = binary.read_text()
            binary.write_text("#!/bin/sh\necho unrelated\nexit 0\n")
            result, outputs = self.step("test3")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs["status"], "failed")
            binary.write_text(original)

    def test_host_and_each_artifact_must_be_native(self):
        result, outputs = self.step("test4")
        self.assertEqual(outputs["status"], "passed")
        for failure in ("host_arch", "artifact_arch"):
            result, outputs = self.step("test4", MOCK_FAILURE=failure)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs["status"], "failed")
        (self.root / "work/bin/baseline/api").unlink()
        result, outputs = self.step("test4")
        self.assertEqual(outputs["status"], "failed")

    def test_functional_failure_or_timeout_propagates_and_cleans(self):
        result, outputs = self.step("test5")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["status"], "passed")
        for failure in ("api_response", "operator_reconcile", "process_exit", "functional_timeout"):
            with self.subTest(failure=failure):
                result, outputs = self.step("test5", MOCK_FAILURE=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["status"], "failed")
                self.assertEqual(list((self.root / "runtime").iterdir()), [])
                self.assertFalse((self.root / "runtime-live").exists())
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        runs = [args for name, args in calls if name == "docker" and "/work/bin/katalis-smoke" in args]
        self.assertEqual(len(runs), 5)
        for args in runs:
            self.assertIn("--init", args)
            self.assertEqual(args[args.index("--network") + 1], "none")
            self.assertIn("no-new-privileges", args)
        removals = [args for name, args in calls if name == "docker" and args[:2] == ["rm", "-f"]]
        self.assertEqual(removals, [["rm", "-f", self.root.name + "-runtime"]] * 4)

    def test_candidate_success_identifies_both_components(self):
        result, outputs = self.step("test6", CURRENT_VERSION="0.0.2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["status"], "passed")
        self.assertEqual(outputs["decision"], "next_install_validated")
        self.assertEqual(outputs["latest_version"], "operator=1.0.2;api=1.0.3")
        self.assertEqual(outputs["next_installed_version"], outputs["latest_version"])
        for key in ("OPERATOR_NEXT_SHA", "API_NEXT_SHA"):
            self.assertIn(self.env[key], outputs["comparison"])

    def test_candidate_errors_never_defer_or_claim_installed(self):
        for failure in ("missing_tag", "source", "download", "checksum", "build", "binary_revision", "tag", "artifact_arch"):
            with self.subTest(failure=failure):
                result, outputs = self.step("test6", CURRENT_VERSION="0.0.2", MOCK_FAILURE=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(outputs["status"], "failed")
                self.assertEqual(outputs["decision"], "next_install_failed")
                self.assertEqual(outputs["next_installed_version"], "operator=not_installed;api=not_installed")

    def test_candidate_rejects_prerelease_and_non_newer_versions(self):
        for version in ("1.1.3-dev", "0.0.2", "0.0.1", ""):
            result, outputs = self.step("test6", CURRENT_VERSION="0.0.2", OPERATOR_NEXT_VERSION=version)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs["status"], "failed")

    def test_candidate_runtime_failure_keeps_verified_install_identity(self):
        for failure in ("api_response", "operator_reconcile", "process_exit"):
            result, outputs = self.step("test6", CURRENT_VERSION="0.0.2", MOCK_FAILURE=failure)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs["status"], "failed")
            self.assertEqual(outputs["decision"], "next_regression_failed")
            self.assertEqual(outputs["next_installed_version"], "operator=1.0.2;api=1.0.3")

    def test_baseline_guard_skips_before_fetch_and_matches_active_policy(self):
        for number in range(1, 6):
            for field, value in (("STATUS", "failed"), ("STATUS", ""), ("OUTCOME", "failure"), ("OUTCOME", "skipped")):
                with self.subTest(number=number, field=field, value=value):
                    result, regression = self.step("test6", CURRENT_VERSION="unknown",
                                                   **{f"BASELINE_{field}_{number}": value})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(regression["status"], "skipped")
                    self.assertEqual(regression["duration"], "0")
                    self.assertEqual(regression["decision"], "baseline_failed")
                    self.assertFalse((self.root / "calls.jsonl").exists())
                    summary_env = {f"STATUS_{i}": "passed" for i in range(1, 7)}
                    summary_env.update({f"OUTCOME_{i}": "success" for i in range(1, 7)})
                    summary_env.update({f"STATUS_{number}": "failed", "STATUS_6": "skipped",
                                        "DURATION_6": "0", "REGRESSION_DECISION": regression["decision"]})
                    result, counts = self.step("summary", **summary_env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual((counts["passed"], counts["failed"], counts["skipped"]), ("4", "1", "1"))
                    details = [{"name": STEPS[f"test{i}"]["name"], "status": summary_env[f"STATUS_{i}"]} for i in range(1, 7)]
                    details[5].update(regression)
                    self.assertEqual(validate_six_test_result(details=details, passed=4, failed=1, skipped=1,
                                                             core_failed=1, decision=regression["decision"]), "failure")

    def test_only_exact_baseline_skip_is_accepted(self):
        env = {f"STATUS_{i}": "passed" for i in range(1, 7)}
        env.update({f"OUTCOME_{i}": "success" for i in range(1, 7)})
        env.update(STATUS_1="failed", STATUS_6="skipped", DURATION_6="0", REGRESSION_DECISION="baseline_failed")
        for override in ({"STATUS_1": "passed"}, {"REGRESSION_DECISION": "manual_review_needed"},
                         {"OUTCOME_6": "failure"}, {"DURATION_6": "1"}, {"STATUS_6": ""}):
            result, outputs = self.step("summary", **{**env, **override})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outputs["skipped"], "0")

    def test_emitted_success_and_candidate_failures_match_active_policy(self):
        for failure in ("", "build", "api_response"):
            result, regression = self.step("test6", CURRENT_VERSION="0.0.2", MOCK_FAILURE=failure)
            details = [{"name": STEPS[f"test{i}"]["name"], "status": "passed"} for i in range(1, 7)]
            details[5].update(regression)
            expected = "failure" if failure else "success"
            self.assertEqual(validate_six_test_result(details=details, passed=5 if failure else 6,
                             failed=1 if failure else 0, skipped=0, core_failed=0,
                             decision=regression["decision"]), expected)

    def test_summary_counters_cover_every_combination(self):
        for passed in itertools.product((False, True), repeat=6):
            env = {}
            for i, success in enumerate(passed, 1):
                env[f"STATUS_{i}"] = "passed" if success else "failed"
                env[f"OUTCOME_{i}"] = "success" if success else "failure"
                env[f"DURATION_{i}"] = str(i)
            result, outputs = self.step("summary", **env)
            self.assertEqual(int(outputs["passed"]), sum(passed))
            self.assertEqual(int(outputs["failed"]), 6 - sum(passed))
            self.assertEqual(int(outputs["core_failed"]), 5 - sum(passed[:5]))
            self.assertEqual(outputs["skipped"], "0")
            self.assertEqual(outputs["duration"], "21")
            self.assertEqual(outputs["badge_status"], "passing" if all(passed[:5]) else "failing")
            self.assertEqual(result.returncode == 0, all(passed))

    def test_missing_outputs_or_failure_outcome_are_failures(self):
        result, outputs = self.step("summary")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outputs["failed"], "6")
        env = {f"STATUS_{i}": "passed" for i in range(1, 7)}
        env.update({f"OUTCOME_{i}": "failure" for i in range(1, 7)})
        result, outputs = self.step("summary", **env)
        self.assertEqual(outputs["failed"], "6")


def native_run(evidence):
    """Replay every YAML run block, honoring step env, outputs and conclusions."""
    if subprocess.check_output(["uname", "-m"], text=True).strip() != "aarch64":
        raise SystemExit("Native execution requires the authorized aarch64 host")
    evidence.mkdir(parents=True, exist_ok=False)
    report = {"workflow_sha256": hashlib.sha256(WORKFLOW.read_bytes()).hexdigest(),
              "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
              "os_release": Path("/etc/os-release").read_text(),
              "uname": subprocess.check_output(["uname", "-a"], text=True).strip(),
              "lscpu": subprocess.check_output(["lscpu"], text=True),
              "steps": {}, "checkout": "Transferred exact local files; checkout action not executed"}
    env = {**os.environ, **JOB["env"], "GITHUB_WORKSPACE": str(ROOT),
           "GITHUB_STEP_SUMMARY": str(evidence / "human-summary.md")}
    previous_failure = False
    for number, step in enumerate(JOB["steps"]):
        if "run" not in step:
            continue
        name = step.get("id", f"step{number}")
        record = {"name": step["name"], "outputs": {}}
        if previous_failure and step.get("if") != "always()":
            record.update(outcome="skipped", conclusion="skipped")
            report["steps"][name] = record
            continue
        output = evidence / f"{name}.output"
        envfile = evidence / f"{name}.env"
        current_env = {**env, "GITHUB_OUTPUT": str(output), "GITHUB_ENV": str(envfile)}
        current_env.update({key: resolve(value, report["steps"]) for key, value in step.get("env", {}).items()})
        script = evidence / f"{name}.sh"
        script.write_text(render(step["run"], report["steps"]))
        print(f"START {name}: {step['name']}", flush=True)
        start = time.monotonic()
        with (evidence / f"{name}.log").open("w") as log:
            result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
                                    cwd=ROOT, env=current_env, stdout=log, stderr=subprocess.STDOUT)
        outcome = "success" if result.returncode == 0 else "failure"
        conclusion = "success" if step.get("continue-on-error") else outcome
        previous_failure = previous_failure or conclusion == "failure"
        record.update(returncode=result.returncode, outcome=outcome, conclusion=conclusion,
                      elapsed_seconds=round(time.monotonic() - start, 3), outputs=read_outputs(output))
        report["steps"][name] = record
        env.update(read_outputs(envfile))
        (evidence / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"END {name}: {outcome} {record['outputs']}", flush=True)
    report["job_outputs"] = {key: resolve(value, report["steps"]) for key, value in JOB["outputs"].items()}
    (evidence / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    return int(previous_failure)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--native-run":
        raise SystemExit(native_run(Path(sys.argv[2]).resolve()))
    unittest.main()
