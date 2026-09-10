"""Exercise the exact Flytectl release workflow without network access."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

import package_observation_migration_audit as audit  # noqa: E402
from package_result_policy import (  # noqa: E402
    BASELINE_REGRESSION_DECISIONS,
    FAILED_REGRESSION_DECISIONS,
    PASSED_REGRESSION_DECISIONS,
    validate_publishable_result,
)


class FlyteWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="flyte-workflow-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        job = yaml.safe_load((ROOT / ".github/workflows/test-flyte.yml").read_text())["jobs"]["test-flyte"]
        self.job = job
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.env = dict(os.environ, **job["env"], GITHUB_OUTPUT=str(self.root / "output"),
                        GITHUB_ENV=str(self.root / "env"), RUNNER_TEMP=str(self.root))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        (self.bin / "python3").symlink_to(sys.executable)
        result, _ = self.run_step("prepare")
        self.assertEqual(0, result.returncode, result.stderr)
        self.env.update(line.split("=", 1) for line in (self.root / "env").read_text().splitlines())
        self.work = Path(self.env["FLYTE_WORK"])
        self.baseline = self.work / "baseline"
        spec = importlib.util.spec_from_file_location("flyte_workflow_probe", self.work / "probe.py")
        self.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.probe)
        page = self.root / self.env["PACKAGE_PAGE"]
        page.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / self.env["PACKAGE_PAGE"], page)
        sdk_bin = self.work / "sdk/bin"
        sdk_bin.mkdir(parents=True)
        sdk_python = sdk_bin / "python"
        sdk_python.write_text(f'#!/bin/bash\nexec {shlex.quote(sys.executable)} "$@"\n')
        sdk_python.chmod(0o755)

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)
        return path

    def run_step(self, step_id, values=None, **environment):
        values = {**self.successful_statuses(), "steps.install.outputs.install_status": "success",
                  "steps.sdk.outcome": "success", **(values or {})}

        script = self.render(self.steps[step_id]["run"], values)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
            env=dict(self.env, **environment), capture_output=True, text=True, timeout=20,
        )
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    @staticmethod
    def render(script, values):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term.strip("'")
                if values.get(term):
                    return values[term]
            return ""

        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)

    def successful_statuses(self):
        return {f"steps.test{i}.{key}": value for i in range(1, 7)
                for key, value in (("outputs.status", "passed"), ("outcome", "success"))}

    def binary_fixture(self):
        return self.stub("flytectl", r'''
case "$1" in
  version)
    if [ "@@{FAIL_VERSION:-0}" != 0 ]; then echo 'version command failed' >&2; exit 7; fi
    printf '%s\n' "$VERSION_PAYLOAD"
    ;;
  --help)
    if [ "@@{FAIL_HELP:-0}" != 0 ]; then echo 'help command failed' >&2; exit 9; fi
    printf '%s\n' 'flytectl [command]' 'compile'
    ;;
  *) echo 'Unexpected CLI command' >&2; exit 90 ;;
esac
'''.replace("@@", "$"))

    def install_fixture(self, version="0.8.19", checksum_mode="valid"):
        self.env["VERSION_PAYLOAD"] = json.dumps({"App": "flytectl", "Version": version})
        binary = self.binary_fixture()
        archive = self.root / "release.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            output.add(binary, arcname="flytectl")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksums = self.root / "checksums.txt"
        line = f"{digest}  flytectl_Linux_arm64.tar.gz\n"
        checksums.write_text({
            "valid": line, "duplicate": line * 2, "missing": "",
            "wrong": "0" * 64 + "  flytectl_Linux_arm64.tar.gz\n",
        }[checksum_mode])
        self.env.update(BASELINE_SHA256=digest, CANDIDATE_SHA256=digest,
                        ARCHIVE_FIXTURE=str(archive), CHECKSUM_FIXTURE=str(checksums),
                        CURL_CALLS=str(self.root / "curl-calls"))
        curl = self.bin / "curl"
        curl.write_text(f"#!{sys.executable}\n" + r'''
import os
from pathlib import Path
import shutil
import sys
url, output = sys.argv[-3], sys.argv[-1]
with open(os.environ["CURL_CALLS"], "a") as log:
    print(url, file=log)
if url.endswith(os.environ.get("FAIL_DOWNLOAD", "never-match")):
    print("HTTP 404: missing release asset", file=sys.stderr)
    sys.exit(22)
key = "CHECKSUM_FIXTURE" if url.endswith("checksums.txt") else "ARCHIVE_FIXTURE"
shutil.copyfile(os.environ[key], output)
''')
        curl.chmod(0o755)

    def install_baseline_fixture(self):
        self.install_fixture()
        result, outputs = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("success", outputs["install_status"])

    def assert_failed(self, result, outputs):
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", outputs["status"])
        self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_catalog_maps_to_namespaced_component_without_changing_baseline(self):
        self.assertEqual("0.8.19", self.env["BASELINE_VERSION"])
        self.assertEqual("0.8.20", self.env["CANDIDATE_VERSION"])
        self.assertIn("flytectl/v{expected}", (self.work / "probe.py").read_text())
        self.assertNotIn("default_branch", self.steps["install"]["run"])
        self.assertNotIn("uses", self.steps["test6"])
        self.assertIn("No Kubernetes backend execution", self.steps["test5"]["run"])

    def test_actual_workflow_outputs_are_visible_to_unchanged_source_auditor(self):
        for number in range(1, 7):
            for output in ("status", "duration"):
                with self.subTest(number=number, output=output):
                    self.assertTrue(audit._step_emits_output(ROOT, self.steps[f"test{number}"], output))
        self.assertEqual(
            {"baseline_failed", "next_install_failed", "limited_cpu_smoke_failed", "limited_cpu_smoke_validated"},
            set(audit._step_literal_outputs(ROOT, self.steps["test6"], "decision")),
        )

    def test_installer_uses_exact_release_checksum_and_runtime_identity(self):
        self.install_baseline_fixture()
        identity = json.loads((self.baseline / "identity.json").read_text())
        self.assertEqual(("flytectl", "flytectl/v0.8.19", "0.8.19"),
                         tuple(identity[key] for key in ("component", "release_tag", "version")))
        self.assertEqual(self.env["BASELINE_SHA256"], identity["archive_sha256"])
        calls = (self.root / "curl-calls").read_text().splitlines()
        self.assertEqual([
            f"https://github.com/flyteorg/flyte/releases/download/flytectl/v0.8.19/{name}"
            for name in ("flytectl_Linux_arm64.tar.gz", "checksums.txt")
        ], calls)
        for step in ("test1", "test2", "test3"):
            result, outputs = self.run_step(step)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("passed", outputs["status"])
            self.assertIn("duration", outputs)

    def test_missing_release_asset_never_falls_back(self):
        for filename in ("flytectl_Linux_arm64.tar.gz", "checksums.txt"):
            with self.subTest(filename=filename):
                shutil.rmtree(self.baseline, ignore_errors=True)
                self.install_fixture()
                result, outputs = self.run_step("install", FAIL_DOWNLOAD=filename)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("HTTP 404", result.stderr)
                self.assertEqual("failed", outputs["install_status"])
                self.assertFalse((self.baseline / "identity.json").exists())
                self.assertNotIn("clone", result.stdout + result.stderr)

    def test_bad_missing_duplicate_and_corrupt_archive_checksums_fail(self):
        for mode in ("wrong", "missing", "duplicate", "corrupt"):
            with self.subTest(mode=mode):
                shutil.rmtree(self.baseline, ignore_errors=True)
                self.install_fixture(checksum_mode="valid" if mode == "corrupt" else mode)
                if mode == "corrupt":
                    Path(self.env["ARCHIVE_FIXTURE"]).write_bytes(b"corrupt")
                result, outputs = self.run_step("install")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["install_status"])
                self.assertIn("checksum mismatch", result.stderr)
                self.assertFalse((self.baseline / "flytectl").exists())

    def test_installer_and_version_check_reject_wrong_missing_and_failed_version(self):
        payloads = [
            (json.dumps({"App": "flytectl", "Version": "0.8.20"}), "0"),
            (json.dumps({"App": "controlPlane", "Version": "0.8.19"}), "0"),
            (json.dumps({"App": "flytectl"}), "0"),
            ("not json", "0"),
            (json.dumps({"App": "flytectl", "Version": "0.8.19"}), "1"),
        ]
        for payload, failed in payloads:
            with self.subTest(payload=payload, failed=failed):
                shutil.rmtree(self.baseline, ignore_errors=True)
                self.install_fixture()
                result, outputs = self.run_step("install", VERSION_PAYLOAD=payload, FAIL_VERSION=failed)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["install_status"])
                self.assertFalse((self.baseline / "identity.json").exists())
                result, outputs = self.run_step("test2", VERSION_PAYLOAD=payload, FAIL_VERSION=failed)
                self.assert_failed(result, outputs)

    def test_catalog_wrong_version_or_component_is_rejected(self):
        self.install_baseline_fixture()
        path = self.root / self.env["PACKAGE_PAGE"]
        original = path.read_text()
        for content in (original.replace("version_number: 0.8.19", "version_number: 0.8.20"),
                        original.replace("flytectl%2Fv0.8.19", "v0.8.19")):
            with self.subTest(content=content):
                path.write_text(content)
                result, outputs = self.run_step("test2")
                self.assert_failed(result, outputs)

    def test_every_core_failure_records_status_and_duration(self):
        for number in range(1, 6):
            with self.subTest(number=number):
                result, outputs = self.run_step(f"test{number}")
                self.assert_failed(result, outputs)

    def test_help_and_sdk_failure_are_not_swallowed(self):
        self.install_baseline_fixture()
        result, outputs = self.run_step("test3", FAIL_HELP="1")
        self.assert_failed(result, outputs)
        self.assertIn("help command failed", result.stderr)
        result, outputs = self.run_step("test5", {"steps.sdk.outcome": "failure"})
        self.assert_failed(result, outputs)
        sdk_python = self.work / "sdk/bin/python"
        sdk_python.unlink()
        sdk_python.write_text("#!/bin/bash\necho 'local workflow execution failed' >&2\nexit 17\n")
        sdk_python.chmod(0o755)
        result, outputs = self.run_step("test5")
        self.assert_failed(result, outputs)
        self.assertIn("local workflow execution failed", result.stderr)

    def test_architecture_requires_native_host_and_real_aarch64_elf(self):
        for machine, evidence, passed in (
            ("x86_64", "ELF 64-bit ARM aarch64", False),
            ("aarch64", "ASCII text", False),
            ("aarch64", "ELF 64-bit x86-64", False),
            ("aarch64", "ELF 64-bit LSB executable, ARM aarch64", True),
        ):
            with self.subTest(machine=machine, evidence=evidence):
                result = subprocess.CompletedProcess([], 0, stdout=evidence)
                with mock.patch.object(self.probe.platform, "machine", return_value=machine), \
                        mock.patch.object(self.probe, "run", return_value=result), \
                        mock.patch("sys.stdout", new_callable=io.StringIO):
                    if passed:
                        self.probe.architecture(Path("flytectl"))
                    else:
                        with self.assertRaises(RuntimeError):
                            self.probe.architecture(Path("flytectl"))

    def test_candidate_missing_wrong_version_and_not_newer_fail_with_truthful_metadata(self):
        for mode in ("missing", "wrong-version", "not-newer"):
            with self.subTest(mode=mode):
                shutil.rmtree(self.work / "candidate", ignore_errors=True)
                self.install_fixture(version="0.8.19" if mode == "wrong-version" else "0.8.20")
                environment = {"FAIL_DOWNLOAD": "flytectl_Linux_arm64.tar.gz"} if mode == "missing" else {}
                if mode == "not-newer":
                    environment["CANDIDATE_VERSION"] = "0.8.19"
                result, outputs = self.run_step("test6", **environment)
                self.assert_failed(result, outputs)
                self.assertEqual("next_install_failed", outputs["decision"])
                self.assertIn(outputs["decision"], FAILED_REGRESSION_DECISIONS)
                self.assertEqual("not_installed", outputs["next_installed_version"])
                self.assertNotIn("passed", outputs["regression_result"])

    def test_candidate_runtime_failure_keeps_observed_installed_version(self):
        self.install_fixture(version="0.8.20")
        result, outputs = self.run_step("test6", FAIL_HELP="1")
        self.assert_failed(result, outputs)
        self.assertEqual("limited_cpu_smoke_failed", outputs["decision"])
        self.assertIn(outputs["decision"], FAILED_REGRESSION_DECISIONS)
        self.assertEqual("0.8.20", outputs["next_installed_version"])
        self.assertIn("help command failed", result.stderr)

    def test_candidate_requires_all_five_baseline_statuses_and_outcomes(self):
        self.install_fixture(version="0.8.20")
        for number in range(1, 6):
            for status, outcome in (("", "success"), ("failed", "success"), ("skipped", "success"),
                                    ("passed", "failure"), ("passed", "cancelled"), ("passed", "")):
                with self.subTest(number=number, status=status, outcome=outcome):
                    values = {f"steps.test{number}.outputs.status": status,
                              f"steps.test{number}.outcome": outcome}
                    result, outputs = self.run_step("test6", values)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("skipped", outputs["status"])
                    self.assertRegex(outputs["duration"], r"^[0-9]+$")
                    self.assertEqual("baseline_failed", outputs["decision"])
                    self.assertIn(outputs["decision"], BASELINE_REGRESSION_DECISIONS)
                    self.assertEqual("not_installed", outputs["next_installed_version"])
                    self.assertFalse((self.root / "curl-calls").exists())
                    values.update({f"steps.test6.outputs.{key}": value for key, value in outputs.items()})
                    values["steps.test6.outcome"] = "success"
                    summary, counts = self.run_step("summary", values)
                    self.assertNotEqual(0, summary.returncode)
                    self.assertEqual(("4", "1", "1", "1"),
                                     tuple(counts[key] for key in ("passed", "failed", "core_failed", "skipped")))
                    self.assertEqual("failure", counts["overall_status"])
                    self.assertEqual("failing", counts["badge_status"])

    def collect_result(self, values, api_steps):
        values = {**{f"env.{key}": value for key, value in self.job["env"].items()},
                  "steps.metadata.outputs.package_slug": "flyte",
                  "steps.version.outputs.version": "0.8.19", "github.job": "test-flyte", **values}
        outputs = {key: self.render(str(value), values) for key, value in self.job["outputs"].items()}
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        with tempfile.TemporaryDirectory(prefix="flyte-collector-") as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(ROOT / ".github/scripts")
            job = {"id": 456, "name": "test-flyte / test-flyte", "steps": api_steps,
                   "conclusion": outputs["run_status"],
                   "html_url": "https://github.com/example/project/actions/runs/123/job/456"}
            env = dict(os.environ, NEEDS_JSON=json.dumps({"test-flyte": {
                "result": outputs["run_status"], "outputs": outputs}}),
                RUN_JOBS_JSON=json.dumps({"jobs": [job]}), BATCH_TITLE="Batch 1", BATCH_NUMBER="1",
                GH_TOKEN="", GITHUB_SERVER_URL="https://github.com", GITHUB_API_URL="https://api.github.com",
                GITHUB_REPOSITORY="example/project", GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1",
                GITHUB_OUTPUT=str(root / "outputs"), GITHUB_STEP_SUMMARY=str(root / "summary"))
            process = subprocess.run([sys.executable, "-B", "-c", source], cwd=root,
                                     env=env, capture_output=True, text=True, timeout=30)
            result = root / "test-results/flyte-test-results/flyte.json"
            return process, json.loads(result.read_text()) if result.exists() else None

    def test_baseline_failure_survives_successful_explanation_step_through_active_collector(self):
        self.install_baseline_fixture()
        baseline, baseline_outputs = self.run_step("test3", FAIL_HELP="1")
        self.assert_failed(baseline, baseline_outputs)
        values = {**self.successful_statuses(), "steps.test3.outcome": "failure",
                  **{f"steps.test3.outputs.{key}": value for key, value in baseline_outputs.items()}}
        candidate, candidate_outputs = self.run_step("test6", values)
        self.assertEqual(0, candidate.returncode)
        self.assertEqual("skipped", candidate_outputs["status"])
        self.assertEqual("baseline_failed", candidate_outputs["decision"])
        values.update({f"steps.test6.outputs.{key}": value for key, value in candidate_outputs.items()})
        values["steps.test6.outcome"] = "success"
        summary, summary_outputs = self.run_step("summary", values)
        self.assertEqual(1, summary.returncode)
        values.update({f"steps.summary.outputs.{key}": value for key, value in summary_outputs.items()})
        for conclusion in ("SUCCESS", "success"):
            with self.subTest(conclusion=conclusion):
                api_steps = [{"name": self.steps[f"test{number}"]["name"], "number": number,
                              "conclusion": "FAILURE" if number == 3 else "SUCCESS"}
                             for number in range(1, 7)]
                api_steps[5]["conclusion"] = conclusion
                process, payload = self.collect_result(values, api_steps)
                self.assertEqual(0, process.returncode, process.stderr)
                self.assertEqual("failure", validate_publishable_result(payload))
                self.assertEqual((4, 1, 1), tuple(payload["tests"][key] for key in ("passed", "failed", "skipped")))
                self.assertEqual(["passed", "passed", "failed", "passed", "passed", "skipped"],
                                 [detail["status"] for detail in payload["tests"]["details"]])
                self.assertEqual("baseline_failed", payload["tests"]["details"][5]["decision"])
                self.assertEqual("failing", payload["metadata"]["badge_status"])
                self.assertEqual(1, payload["metadata"]["core_failed"])
                api_steps[5]["conclusion"] = "FAILURE"
                process, payload = self.collect_result(values, api_steps)
                self.assertNotEqual(0, process.returncode)
                self.assertIsNone(payload)

    def test_summary_accepts_baseline_skip_only_with_core_failure_and_successful_step(self):
        for core_failed, conclusion, decision in (
            (False, "success", "baseline_failed"),
            *((True, conclusion, "baseline_failed") for conclusion in ("failure", "cancelled", "skipped", "")),
            (True, "success", "next_install_failed"), (True, "success", "no_newer_stable_available"),
        ):
            with self.subTest(core_failed=core_failed, conclusion=conclusion, decision=decision):
                values = {"steps.test6.outputs.status": "skipped", "steps.test6.outcome": conclusion,
                          "steps.test6.outputs.decision": decision}
                if core_failed:
                    values["steps.test2.outcome"] = "failure"
                process, summary = self.run_step("summary", values)
                self.assertEqual(1, process.returncode)
                self.assertEqual("0", summary["skipped"])
                self.assertEqual("2" if core_failed else "1", summary["failed"])

    def test_candidate_emits_approved_decisions_for_actual_shell_success_and_failure(self):
        self.install_fixture(version="0.8.20")
        site = self.root / "test-runtime"
        site.mkdir()
        (site / "sitecustomize.py").write_text("import platform\nplatform.machine = lambda: 'aarch64'\n")
        self.stub("file", "echo 'ELF 64-bit LSB executable, ARM aarch64'\n")
        sdk_python = self.work / "sdk/bin/python"
        sdk_python.write_text('#!/bin/bash\necho "SDK smoke fixture"\nexit "${SMOKE_EXIT:-0}"\n')
        for exit_code, decision, policy in (("0", "limited_cpu_smoke_validated", PASSED_REGRESSION_DECISIONS),
                                            ("7", "limited_cpu_smoke_failed", FAILED_REGRESSION_DECISIONS)):
            with self.subTest(exit_code=exit_code):
                shutil.rmtree(self.work / "candidate", ignore_errors=True)
                result, outputs = self.run_step("test6", PYTHONPATH=str(site), SMOKE_EXIT=exit_code)
                self.assertEqual(exit_code == "0", result.returncode == 0, result.stderr)
                self.assertEqual("passed" if exit_code == "0" else "failed", outputs["status"])
                self.assertEqual(decision, outputs["decision"])
                self.assertIn(outputs["decision"], policy)
                self.assertEqual("0.8.20", outputs["next_installed_version"])

    def test_failed_captured_subprocess_prints_error_and_stays_failed(self):
        failure = subprocess.CalledProcessError(7, ["flytectl", "compile"], output="compiler error")
        with mock.patch.object(self.probe.subprocess, "run", side_effect=failure), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(subprocess.CalledProcessError):
                self.probe.run(["flytectl", "compile"], stdout=subprocess.PIPE)
        self.assertIn("compiler error", stderr.getvalue())

    def test_summary_rejects_failed_missing_or_skipped_core(self):
        for number in range(1, 6):
            for status, outcome in (("", "success"), ("skipped", "success"), ("failed", "success"), ("passed", "failure"), ("passed", "cancelled"), ("passed", "")):
                with self.subTest(number=number, status=status, outcome=outcome):
                    values = self.successful_statuses()
                    values.update({f"steps.test{number}.outputs.status": status,
                                   f"steps.test{number}.outcome": outcome})
                    result, outputs = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("5", "1", "1", "failure"), tuple(outputs[key] for key in ("passed", "failed", "core_failed", "overall_status")))

    def test_candidate_failure_and_unapproved_skip_cannot_pass(self):
        for status, outcome, decision in (
            ("failed", "success", "limited_cpu_smoke_failed"),
            ("skipped", "success", "runtime_validation_not_automated"),
            *((status, outcome, decision)
              for status, decision in (("passed", "limited_cpu_smoke_validated"),
                                       ("skipped", "no_newer_stable_available"))
              for outcome in ("failure", "cancelled", "")),
        ):
            with self.subTest(status=status, outcome=outcome, decision=decision):
                values = self.successful_statuses()
                values.update({"steps.test6.outputs.status": status, "steps.test6.outcome": outcome,
                               "steps.test6.outputs.decision": decision})
                result, outputs = self.run_step("summary", values)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("0", outputs["core_failed"])

    def test_six_pass_and_genuine_no_candidate_counts(self):
        for status, decision, passed, skipped in (("passed", "limited_cpu_smoke_validated", "6", "0"), ("skipped", "no_newer_stable_available", "5", "1")):
            values = self.successful_statuses()
            values.update({"steps.test6.outputs.status": status, "steps.test6.outputs.decision": decision})
            result, outputs = self.run_step("summary", values)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual((passed, "0", skipped), tuple(outputs[key] for key in ("passed", "failed", "skipped")))


if __name__ == "__main__":
    unittest.main()
