"""Verify the historical image identity and execute the workflow's failure paths."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-ampere-optimized-llama.yml"
sys.path.insert(0, str(ROOT / ".github/scripts"))
import package_result_policy as policy
import package_observation_migration_audit as audit


class AmpereLlamaWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ampere-llama-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.llm = self.root / "llm"
        self.llm.mkdir()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-ampere-optimized-llama"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = {**os.environ, **self.job["env"], "GH_TOKEN": "",
                    "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "TMPDIR": str(self.root), "FIXTURE": str(self.root)}
        self.values = {
            "steps.install.outputs.install_status": "success",
            "steps.install.outputs.install_mode": "docker_image",
            "steps.install.outputs.image_digest": self.env["BASELINE_IMAGE_DIGEST"],
            "steps.install.outputs.artifact_version": "1.2.0",
            "steps.version.outputs.version": "1.2.0",
        }
        self.values.update({f"steps.test{i}.{key}": value for i in range(1, 6)
                            for key, value in (("outputs.status", "passed"), ("outcome", "success"))})
        self.stub("uname", 'echo "${ARCH:-aarch64}"')
        self.stub("timeout", 'shift; exec "$@"')
        self.stub("date", '''
if [ -f "$FIXTURE/clock" ]; then echo 105; else touch "$FIXTURE/clock"; echo 100; fi
''')
        self.stub("docker", '''
printf '%s\\n' "$*" >> "$FIXTURE/docker-calls"
test "$1" != "${DOCKER_FAIL:-}"
case "$1" in
  manifest) cat "$FIXTURE/manifest.json" ;;
  pull) exit 0 ;;
  image) cat "$FIXTURE/image.json" ;;
  container) test "${CONTAINER_LEFT:-no}" = yes ;;
  rm) test "${REMOVE_FAIL:-no}" = no ;;
  run)
    test "$2" = --rm && test "$3" = --pull && test "$4" = never
    [[ " $* " == *" --cpus 1 --memory 2g --network none "* ]]
    [[ " $* " == *" $PINNED_CONTAINER_IMAGE_LLAMA "* ]]
    script="${!#}"
    script="${script//\\/llm\\//$FIXTURE/llm/}"
    script="${script//\\/start.sh/$FIXTURE/start.sh}"
    script="${script//\\/tmp\\//$FIXTURE/}"
    exec bash -euo pipefail -c "$script"
    ;;
  *) exit 99 ;;
esac
''')
        self.stub("od", 'echo "${ELF_HEADER:-7f454c460201010000000000000000000200b700}"')
        self.stub("git", 'test "${GIT_FAIL:-no}" = no; printf "%s\\n" "${TAGS-abc refs/tags/v3.4.5}"')
        self.stub("curl", '''
test "${CURL_FAIL:-no}" = no
source="$FIXTURE/release.json"
if [[ "$*" == *"/download/"* ]]; then source="$FIXTURE/candidate.tar.gz"; fi
while [ "$1" != -o ]; do shift; done
cp "$source" "$2"
''')
        self.baseline_fixture()
        self.candidate_fixture()

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body + "\n")
        path.chmod(0o755)

    def baseline_fixture(self):
        digest = self.env["BASELINE_IMAGE_DIGEST"]
        self.manifest = {"Descriptor": {"digest": digest, "platform": {"architecture": "arm64", "os": "linux"}}}
        self.image = [{"RepoDigests": [self.env["PINNED_CONTAINER_IMAGE_LLAMA"]], "Architecture": "arm64", "Os": "linux"}]
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))
        (self.root / "image.json").write_text(json.dumps(self.image))
        (self.root / "start.sh").write_text(str(self.llm / "server") + "\n")
        for name in ("main", "server", "test-sampling", "test-quantize-fns"):
            path = self.llm / name
            path.write_text('''#!/bin/bash
set -euo pipefail
name=$(basename "$0")
printf '%s\\n' "$name" >> "$FIXTURE/executed"
if [ "$name" = "${BINARY_FAIL:-}" ]; then exit 17; fi
if [ "$name" = main ] && [ "$1" = --version ]; then
  printf 'version: %s\\n' "${BUILD_VERSION-0 (unknown)}"
  echo "built with Clang for aarch64-unknown-linux-gnu"
fi
if { [ "$name" = main ] || [ "$name" = server ]; } && [ "$1" = --help ]; then
  printf 'usage: %s/llm/%s\\n' "$FIXTURE" "$name"
  echo '--help --model --host'
fi
''')
            path.chmod(0o755)

    def candidate_fixture(self, missing=None, architecture=183):
        name = "llama_aio_v3.4.5_905cccc.tar.gz"
        extracted = self.root / name.removesuffix(".tar.gz")
        if extracted.exists():
            shutil.rmtree(extracted)
        archive = self.root / "candidate.tar.gz"
        with tarfile.open(archive, "w:gz") as package:
            for executable in ("llama-cli", "llama-server", "test-sampling", "test-quantize-fns"):
                if executable == missing:
                    continue
                header = bytearray(20)
                header[:6] = b"\x7fELF\x02\x01"
                header[18:20] = architecture.to_bytes(2, "little")
                entry = tarfile.TarInfo(name.removesuffix(".tar.gz") + "/" + executable)
                entry.mode = 0o755
                entry.size = len(header)
                package.addfile(entry, io.BytesIO(header))
        self.asset = {"name": name, "browser_download_url":
                      "https://github.com/AmpereComputingAI/llama.cpp/releases/download/v3.4.5/" + name,
                      "digest": "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest(),
                      "size": archive.stat().st_size}
        self.release = {"tag_name": "v3.4.5", "draft": False, "prerelease": False, "assets": [self.asset]}
        self.save_candidate_metadata()

    def save_candidate_metadata(self):
        (self.root / "release.json").write_text(json.dumps(self.release))
        (self.root / "asset.json").write_text(json.dumps(self.asset))

    def run_step(self, name, values=None, **environment):
        values = {**self.values, **(values or {})}
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term.strip("'")
                if values.get(term):
                    return values[term]
            return ""
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[name]["run"])
        output = self.root / "output"
        output.write_text("")
        (self.root / "clock").unlink(missing_ok=True)
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
                                env={**self.env, "GITHUB_OUTPUT": str(output), **environment},
                                capture_output=True, text=True, timeout=20)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def python_blocks(self):
        return re.findall(r"^python3 - <<'PY'\n(.*?)^PY$", self.steps["test6"]["run"], re.M | re.S)

    def execute_candidate(self, version="version: 8896 (905ccccf2)\n", failure=None, help_output="--help --model --host"):
        calls = []
        def run(command, **kwargs):
            name = Path(command[0]).name
            calls.append(name)
            self.assertEqual("1", kwargs["env"]["OMP_NUM_THREADS"])
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 180)
            stdout = version if command[-1] == "--version" else help_output
            return subprocess.CompletedProcess(command, 17 if name == failure else 0, stdout=stdout)
        with patch.dict(os.environ, WORK_DIR=str(self.root), NEXT_VERSION="3.4.5"), \
                patch("subprocess.run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            exec(compile(self.python_blocks()[-1], "candidate-runtime", "exec"), {})
        return calls

    def test_baseline_keeps_official_120_digest_and_single_container_pin(self):
        self.assertEqual("1.2.0", self.job["env"]["BASELINE_VERSION"])
        self.assertEqual(["PINNED_CONTAINER_IMAGE_LLAMA"],
                         [key for key in self.job["env"] if key.startswith("PINNED_CONTAINER_IMAGE_")])
        result, output = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("success", "docker_image", "1.2.0"),
                         (output["install_status"], output["install_mode"], output["artifact_version"]))
        result, output = self.run_step("version")
        self.assertEqual((0, "1.2.0"), (result.returncode, output["version"]))
        self.assertIn("embedded_build_version_is_0_unknown", output["version_basis"])

    def test_baseline_missing_wrong_digest_platform_and_pull_fail_closed(self):
        for change in ("missing", "digest", "arch", "os", "pulled_digest", "pulled_arch"):
            with self.subTest(change=change):
                self.baseline_fixture()
                if change == "missing":
                    self.manifest = {}
                elif change == "digest":
                    self.manifest["Descriptor"]["digest"] = "sha256:" + "0" * 64
                elif change in ("arch", "os"):
                    self.manifest["Descriptor"]["platform"]["architecture" if change == "arch" else "os"] = "wrong"
                elif change == "pulled_digest":
                    self.image[0]["RepoDigests"] = []
                else:
                    self.image[0]["Architecture"] = "amd64"
                (self.root / "manifest.json").write_text(json.dumps(self.manifest))
                (self.root / "image.json").write_text(json.dumps(self.image))
                result, output = self.run_step("install")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["install_status"])
                self.assertEqual("unknown", output["artifact_version"])
        self.baseline_fixture()
        for command in ("manifest", "pull", "image"):
            result, output = self.run_step("install", DOCKER_FAIL=command)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", output["install_status"])

    def test_version_cannot_echo_unverified_or_wrong_baseline(self):
        for field, value in (("artifact_version", ""), ("artifact_version", "3.4.5"),
                             ("image_digest", ""), ("image_digest", "sha256:wrong"),
                             ("install_status", "failed")):
            result, output = self.run_step("version", {f"steps.install.outputs.{field}": value})
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("unknown", output["version"])

    def test_install_cleanup_failure_does_not_publish_a_verified_version(self):
        self.stub("rm", "exit 19")
        result, output = self.run_step("install")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("failed", "unknown"), (output["install_status"], output["artifact_version"]))

    def test_five_core_checks_execute_packaged_binaries(self):
        for number in range(1, 6):
            result, output = self.run_step(f"test{number}")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(("passed", "5"), (output["status"], output["duration"]))
        commands = (self.root / "executed").read_text()
        self.assertIn("server", commands)
        self.assertIn("test-sampling", commands)
        self.assertIn("test-quantize-fns", commands)

    def test_missing_runtime_wrong_version_architecture_and_binary_failures_stay_failed(self):
        for step, env in (("test2", {"BUILD_VERSION": ""}), ("test2", {"BUILD_VERSION": "1.2.0"}),
                          ("test2", {"BUILD_VERSION": "3.4.5"}), ("test3", {"BINARY_FAIL": "main"}),
                          ("test3", {"BINARY_FAIL": "server"}), ("test4", {"ARCH": "x86_64"}),
                          ("test4", {"ELF_HEADER": "7f454c4602010100000000000000000002003e00"}),
                          ("test5", {"BINARY_FAIL": "test-sampling"}),
                          ("test5", {"BINARY_FAIL": "test-quantize-fns"})):
            with self.subTest(step=step, env=env):
                result, output = self.run_step(step, **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("failed", "5"), (output["status"], output["duration"]))
        (self.llm / "server").unlink()
        result, output = self.run_step("test1")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])

    def test_docker_and_cleanup_failures_preserve_failure_duration(self):
        for number in range(1, 6):
            result, output = self.run_step(f"test{number}", DOCKER_FAIL="run")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(("failed", "5"), (output["status"], output["duration"]))
        result, output = self.run_step("test1", CONTAINER_LEFT="yes", REMOVE_FAIL="yes")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])
        calls = (self.root / "docker-calls").read_text()
        self.assertIn("rm -f ampere-llama-", calls)
        self.assertNotIn("prune", calls)

    def test_candidate_checks_all_four_executables_and_exact_build_commit(self):
        self.assertEqual(["llama-cli", "llama-cli", "llama-server", "test-sampling", "test-quantize-fns"],
                         self.execute_candidate())
        for version in ("", "version: 0 (unknown)\n", "version: 8896 (abcdef012)\n"):
            with self.subTest(version=version), self.assertRaises(AssertionError):
                self.execute_candidate(version=version)
        for failure in ("llama-cli", "llama-server", "test-sampling", "test-quantize-fns", "timeout"):
            with self.subTest(failure=failure), self.assertRaises((subprocess.CalledProcessError, subprocess.TimeoutExpired)):
                self.execute_candidate(failure=failure)
        with self.assertRaises(AssertionError):
            self.execute_candidate(help_output="nonempty error")

    def test_candidate_rejects_missing_wrong_elf_and_corrupt_download(self):
        for missing in ("llama-cli", "llama-server", "test-sampling", "test-quantize-fns"):
            with self.subTest(missing=missing):
                self.candidate_fixture(missing=missing)
                with self.assertRaises(AssertionError):
                    self.execute_candidate()
        self.candidate_fixture(architecture=62)
        with self.assertRaises(AssertionError):
            self.execute_candidate()
        self.candidate_fixture()
        for field, value in (("size", 1), ("digest", "sha256:" + "0" * 64)):
            self.candidate_fixture()
            self.asset[field] = value
            self.save_candidate_metadata()
            with self.assertRaises(AssertionError):
                self.execute_candidate()

    def test_candidate_wrong_release_asset_or_missing_checksum_fails_before_install(self):
        for field, value in (("tag_name", "v1.2.0"), ("draft", True), ("prerelease", True),
                             ("assets", []), ("digest", None), ("size", 0),
                             ("browser_download_url", "https://example.invalid/llama.tar.gz")):
            with self.subTest(field=field):
                self.candidate_fixture()
                (self.release if field in self.release else self.asset)[field] = value
                self.save_candidate_metadata()
                result, output = self.run_step("test6")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("failed", "not_installed", "5"),
                                 (output["status"], output["next_installed_version"], output["duration"]))

    def test_candidate_lookup_failures_and_real_runtime_failure_do_not_skip(self):
        for env in ({"GIT_FAIL": "yes"}, {"TAGS": ""}, {"TAGS": "abc refs/tags/v1.1.0"},
                    {"TAGS": "abc refs/tags/v3.4.6-rc1"}, {"CURL_FAIL": "yes"}, {}):
            # The final case reaches an actual exec-format error from the fake ELF.
            result, output = self.run_step("test6", **env)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(("failed", "not_installed", "5"),
                             (output["status"], output["next_installed_version"], output["duration"]))

    def test_only_completed_lookup_can_report_no_newer_candidate(self):
        result, output = self.run_step("test6", TAGS="abc refs/tags/v1.2.0")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("skipped", "no_newer_stable_available", "n/a"),
                         (output["status"], output["decision"], output["next_installed_version"]))

    def test_candidate_requires_all_five_baseline_statuses_and_outcomes(self):
        self.assertEqual("always()", self.steps["test6"]["if"])
        for number in range(1, 6):
            for status, outcome in (("", "success"), ("failed", "success"), ("skipped", "success"),
                                    ("passed", "failure"), ("passed", ""), ("passed", "skipped"),
                                    ("passed", "cancelled")):
                result, output = self.run_step("test6", {
                    f"steps.test{number}.outputs.status": status, f"steps.test{number}.outcome": outcome},
                    TAGS="abc refs/tags/v1.2.0")
                self.assertEqual(0, result.returncode)
                self.assertEqual(("skipped", "baseline_failed", "unknown", "not_installed", "5"),
                                 (output["status"], output["decision"], output["latest_version"],
                                  output["next_installed_version"], output["duration"]))

    def test_late_candidate_cleanup_failure_overwrites_success_and_skip(self):
        self.stub("rm", "exit 19")
        for skip in (False, True):
            with self.subTest(skip=skip):
                # Runtime behavior is covered above; isolate the subsequent shell cleanup here.
                if not skip:
                    block = self.python_blocks()[-1]
                    self.steps["test6"]["run"] = self.steps["test6"]["run"].replace(block, "print('runtime fixture completed')\n")
                result, output = self.run_step("test6", TAGS="abc refs/tags/v1.2.0" if skip else "abc refs/tags/v3.4.5")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("failed", "limited_cpu_smoke_failed", "5"),
                                 (output["status"], output["decision"], output["duration"]))

    def test_emitted_candidate_decisions_match_existing_policy(self):
        for branch in ("passed", "failed", "baseline", "no_newer"):
            original = self.steps["test6"]["run"]
            values = {}
            environment = {}
            if branch == "passed":
                # The extracted runtime is exercised independently with binary-level fixtures.
                self.steps["test6"]["run"] = original.replace(self.python_blocks()[-1], "print('runtime fixture completed')\n")
            elif branch == "failed":
                environment["CURL_FAIL"] = "yes"
            elif branch == "baseline":
                values["steps.test3.outputs.status"] = "failed"
                values["steps.test3.outcome"] = "failure"
            else:
                environment["TAGS"] = "abc refs/tags/v1.2.0"
            result, output = self.run_step("test6", values, **environment)
            self.steps["test6"]["run"] = original
            groups = {"passed": policy.PASSED_REGRESSION_DECISIONS,
                      "failed": policy.FAILED_REGRESSION_DECISIONS,
                      "baseline": policy.BASELINE_REGRESSION_DECISIONS,
                      "no_newer": policy.NOT_APPLICABLE_REGRESSION_DECISIONS}
            self.assertIn(output["decision"], groups[branch])
            semantic = policy.expected_regression_metadata(decision=output["decision"], core_failed=int(branch == "baseline"))
            raw = {"not_applicable": "skipped", "skipped": "skipped"}.get(semantic["status"], semantic["status"])
            self.assertEqual(raw, output["status"])
            self.assertEqual(branch in ("passed", "baseline", "no_newer"), result.returncode == 0)
            summary_values = {f"steps.test{i}.{key}": value for i in range(1, 7)
                              for key, value in (("outputs.status", "passed"), ("outcome", "success"))}
            summary_values.update(values)
            summary_values.update({f"steps.test6.outputs.{key}": value for key, value in output.items()})
            summary_values["steps.test6.outcome"] = "success" if result.returncode == 0 else "failure"
            summary_result, summary = self.run_step("summary", summary_values)
            self.assertEqual(semantic["run_status"], summary["overall_status"])
            self.assertEqual(semantic["run_status"] == "success", summary_result.returncode == 0)
            details = [{"name": f"Test {i}", "status": summary_values[f"steps.test{i}.outputs.status"]}
                       for i in range(1, 7)]
            details[5]["decision"] = output["decision"]
            self.assertEqual(semantic["run_status"], policy.validate_six_test_result(
                details=details, decision=output["decision"],
                **{key: int(summary[key]) for key in ("passed", "failed", "skipped", "core_failed")}))


    def test_baseline_skip_survives_active_collector_and_unchanged_policy(self):
        values = {f"steps.test{i}.{key}": value for i in range(1, 7)
                  for key, value in (("outputs.status", "passed"), ("outcome", "success"))}
        values.update({"steps.test3.outputs.status": "failed", "steps.test3.outcome": "failure"})
        result, regression = self.run_step("test6", values)
        self.assertEqual(0, result.returncode, result.stderr)
        values.update({f"steps.test6.outputs.{key}": value for key, value in regression.items()})
        values["steps.test6.outcome"] = "success"
        result, summary = self.run_step("summary", values)
        self.assertEqual(1, result.returncode)
        self.assertEqual(("4", "1", "1", "failure"),
                         tuple(summary[key] for key in ("passed", "failed", "skipped", "overall_status")))
        slug = "ampere-optimized-llama"
        need = {"result": "failure", "outputs": {
            "contract_version": "2.0", "package_slug": slug, "package_name": "Ampere Optimized Llama.cpp",
            "package_version": "1.2.0", "job_name": "test-" + slug,
            "run_status": summary["overall_status"], "badge_status": summary["badge_status"],
            "tests_passed": summary["passed"], "tests_failed": summary["failed"],
            "tests_skipped": summary["skipped"], "core_failed": summary["core_failed"],
            "regression_status": regression["status"], "regression_decision": regression["decision"],
            "regression_result": regression["regression_result"], "regression_comparison": regression["comparison"],
            "regression_current_version": regression["current_version"],
            "regression_latest_version": regression["latest_version"],
            "regression_next_installed_version": regression["next_installed_version"],
        }}
        job = {"id": 456, "name": f"test-{slug} / test-{slug}", "conclusion": "failure",
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "steps": [{"name": self.steps[f"test{i}"]["name"], "number": i,
                          "conclusion": "failure" if i == 3 else "success"} for i in range(1, 7)]}
        job["steps"].append({"name": "Calculate test summary", "number": 7, "conclusion": "failure"})
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        directory = self.root / "collector"
        (directory / ".github").mkdir(parents=True)
        (directory / ".github/scripts").symlink_to(ROOT / ".github/scripts")
        environment = {**os.environ, "NEEDS_JSON": json.dumps({"test-" + slug: need}),
                       "BATCH_NUMBER": "1", "BATCH_TITLE": "Batch 1", "GH_TOKEN": "",
                       "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
                       "GITHUB_REPOSITORY": "example/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                       "GITHUB_OUTPUT": str(directory / "output"), "GITHUB_STEP_SUMMARY": str(directory / "summary")}
        payload_path = directory / f"test-results/{slug}-test-results/{slug}.json"
        for conclusion in ("success", "failure"):
            job["steps"][5]["conclusion"] = conclusion
            payload_path.unlink(missing_ok=True)
            collected = subprocess.run([sys.executable, "-B", "-c", source], cwd=directory,
                                       env={**environment, "RUN_JOBS_JSON": json.dumps({"jobs": [job]})},
                                       capture_output=True, text=True, timeout=30)
            if conclusion == "failure":
                self.assertNotEqual(0, collected.returncode)
                self.assertFalse(payload_path.exists())
                continue
            self.assertEqual(0, collected.returncode, collected.stderr)
            payload = json.loads(payload_path.read_text())
            self.assertEqual(["passed", "passed", "failed", "passed", "passed", "skipped"],
                             [detail["status"] for detail in payload["tests"]["details"]])
            self.assertEqual("baseline_failed", payload["tests"]["details"][5]["decision"])
            self.assertEqual("failure", policy.validate_publishable_result(payload))

    def test_audit_sees_only_policy_coherent_decision_status_pairs(self):
        self.assertEqual((("baseline_failed", "skipped"), ("limited_cpu_smoke_failed", "failed"),
                          ("limited_cpu_smoke_validated", "passed"), ("no_newer_stable_available", "skipped")),
                         audit._step_literal_pairs(ROOT, self.steps["test6"]))
        for number in range(1, 7):
            for output in ("status", "duration"):
                self.assertTrue(audit._step_emits_output(ROOT, self.steps[f"test{number}"], output))

    def test_summary_requires_all_core_successes_and_actual_outcomes(self):
        values = {f"steps.test{i}.{key}": value for i in range(1, 7)
                  for key, value in (("outputs.status", "passed"), ("outcome", "success"), ("outputs.duration", "5"))}
        result, output = self.run_step("summary", values)
        self.assertEqual((0, "6", "30"), (result.returncode, output["passed"], output["duration"]))
        for number in range(1, 7):
            for status, outcome in (("", "success"), ("passed", "failure"), ("passed", "cancelled"),
                                    ("passed", ""), ("failed", "success"), ("skipped", "success")):
                changed = {**values, f"steps.test{number}.outputs.status": status,
                           f"steps.test{number}.outcome": outcome}
                result, output = self.run_step("summary", changed)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", output["failed"])
                self.assertEqual(str(int(number <= 5)), output["core_failed"])


if __name__ == "__main__":
    unittest.main()
