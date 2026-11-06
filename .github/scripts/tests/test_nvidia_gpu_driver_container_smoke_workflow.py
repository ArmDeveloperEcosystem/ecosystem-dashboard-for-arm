"""Execute NVIDIA's embedded registry resolver and summary with offline fixtures."""

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPTS))
import package_result_policy as policy
import promote_package_results as publisher

WORKFLOW = ROOT / ".github/workflows/test-nvidia-gpu-driver-container.yml"
REPOSITORY = "nvcr.io/nvidia/driver"
BASELINE = "535.288.01"
CANDIDATE = "615.71.09"
SCOPE = "No driver installation, kernel module load, privileged container, CUDA or GPU execution was tested."


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class NvidiaDriverSmokeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nvidia-driver-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.job = self.workflow["jobs"]["test-nvidia-gpu-driver-container"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.source = self.job["env"]["SCOPED_ARM_PREFLIGHT_PROBE"].split(
            "python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        self.calls = []
        self.failure = ""
        self.images = {}
        for version in (BASELINE, CANDIDATE):
            config = {"architecture": "arm64", "os": "linux",
                      "config": {"Env": ["TARGETARCH=arm64", "DRIVER_VERSION=" + version],
                                 "Entrypoint": ["nvidia-driver", "init"]}}
            config_digest = digest(encoded(config))
            manifest = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "config": {"digest": config_digest, "size": len(encoded(config))},
                        "layers": [{"digest": "sha256:" + "1" * 64, "size": 100}]}
            child = encoded(manifest)
            index = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
                     "manifests": [
                         {"mediaType": manifest["mediaType"], "digest": "sha256:" + "2" * 64,
                          "size": 123, "platform": {"os": "linux", "architecture": "amd64"}},
                         {"mediaType": manifest["mediaType"], "digest": digest(child),
                          "size": len(child), "platform": {"os": "linux", "architecture": "arm64"}}]}
            self.images[version] = {"config": config, "config_digest": config_digest,
                                    "manifest": manifest, "child": child, "index": index}
        self.values = {f"steps.test{i}.{key}": value for i in range(1, 7)
                       for key, value in (("outputs.status", "passed"), ("outcome", "success"))}
        self.values.update({"steps.test6.outputs.decision": "limited_cpu_smoke_validated",
                            "steps.test6.outputs.regression_result": "Native image payload checked",
                            "steps.test6.outputs.comparison": SCOPE,
                            "steps.test6.outputs.current_version": BASELINE,
                            "steps.test6.outputs.latest_version": CANDIDATE,
                            "steps.test6.outputs.next_installed_version": CANDIDATE})

    def fields(self):
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def fixture(self, args, **kwargs):
        self.calls.append(args)
        if args[:2] == ["docker", "rm"]:
            return subprocess.CompletedProcess(args, 0, stdout=b"")
        if args[0] == "skopeo":
            self.assertIn("--no-creds", args)
            self.assertIn("--tls-verify=true", args)
            self.assertNotIn("GH_TOKEN", kwargs["env"])
            self.assertNotIn("GITHUB_TOKEN", kwargs["env"])
            self.assertTrue(args[-1].startswith("docker://" + REPOSITORY))
            if self.failure == "registry_error":
                raise subprocess.CalledProcessError(22, args, stderr=b"401")
            if self.failure == "registry_timeout":
                raise subprocess.TimeoutExpired(args, 120)
            if args[1] == "list-tags":
                data = {"Repository": REPOSITORY, "Tags": [
                    BASELINE + "-ubuntu22.04", CANDIDATE + "-ubuntu22.04",
                    "999.0.0-ubuntu24.04", "999.0.0-ubuntu22.04-rc1",
                    "999-6.8.0-90-generic-ubuntu22.04", "610.57.04-ubuntu22.04"]}
                if self.failure == "bad_tags": data["Tags"] = "not a list"
                if self.failure == "tags_not_object": data = []
                if self.failure == "wrong_repository": data["Repository"] = "example/driver"
                if self.failure == "empty_tags": data["Tags"] = []
                if self.failure == "no_newer": data["Tags"] = [BASELINE + "-ubuntu22.04"]
                if self.failure == "bad_json": return subprocess.CompletedProcess(args, 0, stdout=b"{")
                result = encoded(data)
            else:
                reference = args[-1].removeprefix("docker://")
                version = next((v for v, item in self.images.items()
                                if reference.endswith(":" + v + "-ubuntu22.04")
                                or reference.endswith("@" + digest(encoded(item["index"])))
                                or reference.endswith("@" + digest(item["child"]))), None)
                self.assertIsNotNone(version, reference)
                item = self.images[version]
                if "--config" in args:
                    config = copy.deepcopy(item["config"])
                    if self.failure == "wrong_config_arch": config["architecture"] = "amd64"
                    if self.failure == "wrong_config_version": config["config"]["Env"][1] = "DRIVER_VERSION=0.0.0"
                    if self.failure == "bad_config": config = {}
                    if self.failure == "config_not_object": config = []
                    if self.failure == "config_null": config["config"] = None
                    if self.failure == "conflicting_env": config["config"]["Env"].append("DRIVER_VERSION=0.0.0")
                    if self.failure == "bad_entrypoint": config["config"]["Entrypoint"] = ["sh"]
                    result = json.dumps(config, indent=4).encode()  # Normalized config is not hashed.
                elif reference.endswith("@" + digest(item["child"])):
                    result = item["child"]
                    if self.failure == "child_digest": result += b" "
                    if self.failure == "child_error": raise subprocess.CalledProcessError(1, args)
                else:
                    index = copy.deepcopy(item["index"])
                    if self.failure == "no_arm": index["manifests"] = index["manifests"][:1]
                    if self.failure == "duplicate_arm": index["manifests"].append(index["manifests"][1])
                    if self.failure == "wrong_os": index["manifests"][1]["platform"]["os"] = "windows"
                    if self.failure == "bad_index": index["manifests"] = "not a list"
                    if self.failure == "bad_platform": index["manifests"][1]["platform"] = None
                    if self.failure == "bad_digest": index["manifests"][1]["digest"] = "not-a-digest"
                    if self.failure == "bad_schema": index["schemaVersion"] = 1
                    if self.failure == "size_mismatch": index["manifests"][1]["size"] += 1
                    if self.failure == "index_not_object": index = []
                    result = encoded(index)
                    if self.failure == "index_digest": result += b" "
            return subprocess.CompletedProcess(args, 0, stdout=result)
        self.assertEqual("docker", args[0])
        if args[1] == "pull":
            self.assertEqual(["--platform", "linux/arm64"], args[2:4])
            self.assertRegex(args[4], r"^nvcr\.io/nvidia/driver@sha256:[a-f0-9]{64}$")
            if self.failure == "pull_error": raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, stdout=b"pulled")
        if args[1:3] == ["image", "inspect"]:
            item = next(item for item in self.images.values()
                        if args[-1].endswith("@" + digest(item["child"])))
            data = {"Id": item["config_digest"], "Architecture": "arm64", "Os": "linux"}
            if self.failure == "pulled_id": data["Id"] = "sha256:" + "0" * 64
            if self.failure == "pulled_arch": data["Architecture"] = "amd64"
            return subprocess.CompletedProcess(args, 0, stdout=encoded([data]))
        self.assertEqual("run", args[1])
        pairs = {"--network": "none", "--user": "65534:65534", "--runtime": "runc",
                 "--platform": "linux/arm64", "--entrypoint": "/bin/bash",
                 "--cap-drop": "ALL", "--security-opt": "no-new-privileges",
                 "--cpus": "2", "--memory": "512m", "--pids-limit": "64"}
        for flag, expected in pairs.items():
            self.assertEqual(expected, args[args.index(flag) + 1])
        self.assertIn("--read-only", args)
        self.assertIn("--pull=never", args)
        for forbidden in ("--privileged", "--gpus", "--device", "-v", "--mount", "-e", "--env"):
            self.assertNotIn(forbidden, args)
        script = args[args.index("-euc") + 1]
        self.assertIn('sh "$installer" --check', script)
        self.assertIn("bash -n /usr/local/bin/nvidia-driver", script)
        self.assertNotIn("--accept", script)
        self.assertNotIn("--extract", script)
        if self.failure == "run_error": raise subprocess.CalledProcessError(7, args)
        if self.failure == "run_timeout": raise subprocess.TimeoutExpired(args, 180)
        result = f"DRIVER_PREFLIGHT_OK version={args[-1]} arch=aarch64 checksum=verified\n".encode()
        if self.failure == "missing_proof": result = b"metadata exists"
        return subprocess.CompletedProcess(args, 0, stdout=result)

    def run_probe(self, mode="candidate", failure="", system="Linux", machine="aarch64", **overrides):
        self.failure = failure
        self.calls = []
        self.output.write_text("")
        env = {**os.environ, **self.job["env"], "DRIVER_PREFLIGHT_MODE": mode,
               "GITHUB_OUTPUT": str(self.output), "GH_TOKEN": "not-for-registry",
               "GITHUB_TOKEN": "not-for-payload",
               "PINNED_CONTAINER_IMAGE_NVIDIA_DRIVER":
                   REPOSITORY + "@" + digest(encoded(self.images[BASELINE]["index"])),
               **overrides}
        code = 0
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("platform.system", return_value=system), \
                mock.patch("platform.machine", return_value=machine), \
                mock.patch("subprocess.run", side_effect=self.fixture), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                exec(compile(self.source, str(WORKFLOW), "exec"), {"__name__": "__main__"})
            except SystemExit as exc:
                code = exc.code
        return code, self.fields()

    def render(self, text, overrides=None):
        values = {**self.values, **(overrides or {})}
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else values.get(term, "")
                if value:
                    return value
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, str(text))

    def run_step(self, name, values=None, **environment):
        self.output.write_text("")
        step = self.steps[name]
        env = {**os.environ, **self.job["env"], "GITHUB_OUTPUT": str(self.output),
               **{k: self.render(v, values) for k, v in step.get("env", {}).items()},
               **environment}
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c",
                                 self.render(step["run"], values)], cwd=self.root, env=env,
                                text=True, capture_output=True, timeout=15)
        return result, self.fields()

    def test_baseline_metadata_and_pin_are_unchanged(self):
        self.assertEqual(BASELINE, self.job["env"]["BASELINE_VERSION"])
        self.assertEqual(REPOSITORY + "@sha256:21b0c912d4c71f1166c68d4c7e26d28981f0e9d1de5ed00c332e00fdbde41b15",
                         self.job["env"]["PINNED_CONTAINER_IMAGE_NVIDIA_DRIVER"])
        self.assertIn("# original: " + REPOSITORY + ":" + BASELINE + "-ubuntu22.04", WORKFLOW.read_text())
        result, fields = self.run_step("test2", {"steps.expectations.outputs.content_page":
                    str(ROOT / "content/linux/opensource_packages/nvidia-gpu-driver-container.md")})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", fields["status"])

    def test_baseline_and_candidate_execute_digest_bound_native_payload(self):
        for mode in ("baseline", "candidate"):
            with self.subTest(mode=mode):
                code, fields = self.run_probe(mode)
                self.assertEqual(0, code)
                self.assertEqual(1, sum(c[:2] == ["docker", "run"] for c in self.calls))
                if mode == "candidate":
                    self.assertEqual("passed", fields["status"])
                    self.assertEqual("limited_cpu_smoke_validated", fields["decision"])
                    self.assertEqual(CANDIDATE, fields["next_installed_version"])
                    self.assertIn(SCOPE, fields["comparison"])
                    self.assertIn("index=sha256:", fields["comparison"])
                    self.assertIn("config=sha256:", fields["comparison"])

    def test_bad_metadata_is_deferred_without_payload_or_fabricated_observed_version(self):
        for failure in ("registry_error", "registry_timeout", "bad_json", "bad_tags",
                        "tags_not_object", "wrong_repository", "empty_tags", "no_arm", "duplicate_arm",
                        "wrong_os", "bad_index", "index_not_object", "bad_platform", "bad_digest", "bad_schema", "size_mismatch",
                        "child_digest", "child_error", "wrong_config_arch",
                        "wrong_config_version", "bad_config", "config_not_object", "config_null",
                        "conflicting_env", "bad_entrypoint"):
            with self.subTest(failure=failure):
                code, fields = self.run_probe(failure=failure)
                self.assertEqual(0, code)
                self.assertEqual(("skipped", "metadata_review_required", "not_installed"),
                                 tuple(fields[k] for k in ("status", "decision", "next_installed_version")))
                self.assertFalse(any(c[0] == "docker" for c in self.calls))
                self.assertIn("Deferred:", fields["comparison"])

    def test_no_newer_requires_complete_valid_inventory(self):
        code, fields = self.run_probe(failure="no_newer")
        self.assertEqual(0, code)
        self.assertEqual(("skipped", "no_newer_stable_available", BASELINE, "n/a"),
                         tuple(fields[k] for k in ("status", "decision", "latest_version", "next_installed_version")))
        self.assertEqual(1, len(self.calls))

    def test_docker_manifest_list_and_single_arm_image_are_verified(self):
        models = copy.deepcopy(self.images)
        for kind in ("docker-list", "single-arm"):
            with self.subTest(kind=kind):
                self.images = copy.deepcopy(models)
                for item in self.images.values():
                    if kind == "docker-list":
                        item["index"]["mediaType"] = "application/vnd.docker.distribution.manifest.list.v2+json"
                        item["manifest"]["mediaType"] = "application/vnd.docker.distribution.manifest.v2+json"
                        item["child"] = encoded(item["manifest"])
                        item["index"]["manifests"][1].update(
                            mediaType=item["manifest"]["mediaType"], digest=digest(item["child"]),
                            size=len(item["child"]))
                    else:
                        item["index"] = copy.deepcopy(item["manifest"])
                code, fields = self.run_probe()
                self.assertEqual(0, code)
                self.assertEqual("passed", fields["status"])

    def test_non_native_host_cannot_claim_an_arm_payload_pass(self):
        for system, machine in (("Linux", "x86_64"), ("Darwin", "arm64")):
            with self.subTest(system=system, machine=machine):
                code, fields = self.run_probe(system=system, machine=machine)
                self.assertEqual(1, code)
                self.assertEqual("failed", fields["status"])
                self.assertFalse(self.calls)

    def test_payload_failures_are_not_downgraded_to_deferred_or_passed(self):
        for failure in ("pull_error", "pulled_id", "pulled_arch", "run_error",
                        "run_timeout", "missing_proof"):
            with self.subTest(failure=failure):
                code, fields = self.run_probe(failure=failure)
                self.assertEqual(1, code)
                self.assertEqual(("failed", "limited_cpu_smoke_failed", "not_installed"),
                                 tuple(fields[k] for k in ("status", "decision", "next_installed_version")))
                if failure.startswith("run_") or failure == "missing_proof":
                    self.assertEqual(["docker", "rm", "-f"], self.calls[-1][:3])

    def test_changed_baseline_digest_fails_before_container_execution(self):
        code, _ = self.run_probe("baseline", failure="index_digest")
        self.assertNotEqual(0, code)
        self.assertFalse(any(c[0] == "docker" for c in self.calls))

    def test_wrappers_emit_failure_and_duration_for_unhandled_probe_errors(self):
        for step in ("test5", "test6"):
            with self.subTest(step=step):
                result, fields = self.run_step(step, SCOPED_ARM_PREFLIGHT_PROBE="exit 23")
                self.assertEqual(23, result.returncode, result.stderr)
                self.assertEqual("failed", fields["status"])
                self.assertTrue(fields["duration"].isdigit())

    def test_candidate_baseline_guard_never_invokes_probe(self):
        result, fields = self.run_step("test6", {"steps.test5.outcome": "failure",
                         "steps.test5.outputs.status": ""}, SCOPED_ARM_PREFLIGHT_PROBE="exit 97")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("skipped", "baseline_failed"),
                         tuple(fields[k] for k in ("status", "decision")))

    def test_summary_pass_and_no_newer_have_exact_counts(self):
        for status, decision, counts in (
                ("passed", "limited_cpu_smoke_validated", ("6", "0", "0")),
                ("skipped", "no_newer_stable_available", ("5", "0", "1"))):
            with self.subTest(decision=decision):
                result, fields = self.run_step("summary", {"steps.test6.outputs.status": status,
                                      "steps.test6.outputs.decision": decision})
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(counts, tuple(fields[k] for k in ("passed", "failed", "skipped")))
                self.assertEqual("success", fields["overall_status"])

    def test_summary_missing_cancelled_or_contradictory_baseline_fails_closed(self):
        for index in range(1, 6):
            for status, outcome in (("", "success"), ("passed", ""), ("passed", "failure"),
                                    ("passed", "cancelled"), ("skipped", "skipped"),
                                    ("invalid", "success"), ("failed", "success")):
                with self.subTest(index=index, status=status, outcome=outcome):
                    result, fields = self.run_step("summary", {
                        f"steps.test{index}.outputs.status": status, f"steps.test{index}.outcome": outcome})
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("4", "1", "1", "1"), tuple(fields[k] for k in
                                     ("passed", "failed", "skipped", "core_failed")))
                    self.assertEqual("failed", fields[f"test{index}_status"])
                    self.assertEqual("baseline_failed", fields["regression_decision"])

    def test_summary_positive_branches_require_nonblank_evidence_text(self):
        for status, decision in (("passed", "limited_cpu_smoke_validated"),
                                 ("skipped", "no_newer_stable_available")):
            for key in ("regression_result", "comparison"):
                for value in ("", " \t "):
                    with self.subTest(status=status, key=key, value=value):
                        result, fields = self.run_step("summary", {
                            "steps.test6.outputs.status": status,
                            "steps.test6.outputs.decision": decision,
                            f"steps.test6.outputs.{key}": value})
                        self.assertNotEqual(0, result.returncode)
                        self.assertEqual(("5", "1", "0"),
                                         tuple(fields[k] for k in ("passed", "failed", "skipped")))
                        self.assertEqual("next_regression_failed", fields["regression_decision"])
                        self.assertEqual("failing", fields["badge_status"])

    def test_summary_deferred_and_invalid_candidate_is_not_green(self):
        for status, decision, outcome in (
                ("skipped", "metadata_review_required", "success"),
                ("passed", "limited_cpu_smoke_validated", "cancelled"),
                ("passed", "limited_cpu_smoke_validated", "failure"),
                ("", "", "success"), ("passed", "", "success"),
                ("skipped", "invented", "success"), ("passed", "no_newer_stable_available", "success"),
                ("failed", "limited_cpu_smoke_failed", "failure")):
            with self.subTest(status=status, decision=decision, outcome=outcome):
                result, fields = self.run_step("summary", {"steps.test6.outputs.status": status,
                                "steps.test6.outputs.decision": decision, "steps.test6.outcome": outcome})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("5", "1", "0"), tuple(fields[k] for k in ("passed", "failed", "skipped")))
                self.assertEqual("failure", fields["overall_status"])
                self.assertEqual("failing", fields["badge_status"])
                if decision == "metadata_review_required":
                    self.assertIn("Deferred candidate evidence (metadata_review_required)", fields["regression_comparison"])
                    self.assertEqual("next_regression_failed", fields["regression_decision"])

    def test_all_six_steps_keep_actual_failure_conclusions_visible(self):
        for i in range(1, 7):
            self.assertEqual("always()", self.steps[f"test{i}"]["if"])
            self.assertNotIn("continue-on-error", self.steps[f"test{i}"])
        self.assertIn("skopeo", next(s["with"]["packages"] for s in self.job["steps"]
                                    if s.get("uses") == "./.github/actions/apt-bootstrap"))
        self.assertEqual(30, self.job["timeout-minutes"])



    def collect(self, summary, regression, conclusions):
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        bindings = {**{f"steps.test6.outputs.{k}": v for k, v in regression.items()},
                    **{f"steps.summary.outputs.{k}": v for k, v in summary.items()},
                    "steps.version.outputs.version": BASELINE,
                    "steps.metadata.outputs.package_slug": "nvidia-gpu-driver-container",
                    "steps.metadata.outputs.dashboard_link": "/linux/opensource_packages/nvidia-gpu-driver-container",
                    "steps.metadata.outputs.timestamp": "2026-10-28T16:00:01Z",
                    "github.run_id": "123", "github.run_attempt": "1",
                    "github.job": "test-nvidia-gpu-driver-container"}
        outputs = {k: self.render(v, bindings) for k, v in self.job["outputs"].items()}
        job = {"id": 456, "name": "test-nvidia-gpu-driver-container / test-nvidia-gpu-driver-container",
               "conclusion": summary["overall_status"],
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "started_at": "2026-10-28T16:00:00Z", "completed_at": "2026-10-28T16:01:00Z",
               "steps": [{"name": self.steps[f"test{i}"]["name"], "number": i, "conclusion": conclusion}
                         for i, conclusion in enumerate(conclusions, 1)]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(SCRIPTS)
            self.output.write_text("")
            process = subprocess.run([sys.executable, "-B", "-c", source], cwd=root,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GITHUB_OUTPUT": str(self.output),
                     "NEEDS_JSON": json.dumps({"test-nvidia-gpu-driver-container":
                         {"result": summary["overall_status"], "outputs": outputs}}),
                     "RUN_JOBS_JSON": json.dumps({"jobs": [job]}),
                     "BATCH_NUMBER": "20", "BATCH_TITLE": "Batch 20",
                     "GH_TOKEN": "", "GITHUB_TOKEN": "", "GITHUB_SERVER_URL": "https://github.com",
                     "GITHUB_STEP_SUMMARY": str(root / "summary"),
                     "GITHUB_API_URL": "https://api.github.com", "GITHUB_REPOSITORY": "example/project",
                     "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"},
                capture_output=True, text=True, timeout=30)
            path = root / "test-results/nvidia-gpu-driver-container-test-results/nvidia-gpu-driver-container.json"
            payload = json.loads(path.read_text()) if path.exists() else None
        registration = {"batch_title": "Batch 20", "workflow_path": ".github/workflows/test-all-packages-batch20.yml",
                        "run_id": "123", "run_attempt": "1", "job_name": job["name"], "job_url": job["html_url"],
                        "job_conclusion": job["conclusion"], "job_started_at": job["started_at"],
                        "job_completed_at": job["completed_at"], "resolution_status": "central_exact"}
        return process, payload, registration

    def test_active_collector_and_strict_publisher_round_trip_exact_counts_and_scope(self):
        for failure, conclusion, counts in (
                ("", "success", (6, 0, 0)), ("no_newer", "success", (5, 0, 1)),
                ("run_error", "failure", (5, 1, 0)), ("no_arm", "success", (5, 1, 0))):
            with self.subTest(failure=failure):
                _, regression = self.run_probe(failure=failure)
                values = {**{f"steps.test6.outputs.{k}": v for k, v in regression.items()},
                          "steps.test6.outcome": conclusion}
                _, summary = self.run_step("summary", values)
                process, payload, registration = self.collect(summary, regression, ["success"] * 5 + [conclusion])
                self.assertEqual(0, process.returncode, process.stdout + process.stderr)
                self.assertEqual(counts, tuple(payload["tests"][k] for k in ("passed", "failed", "skipped")))
                self.assertIn("(CPU-only image preflight)", payload["package"]["name"])
                self.assertIn(SCOPE, payload["tests"]["details"][5]["comparison"])
                expected = "failure" if counts[1] else "success"
                self.assertEqual(expected, policy.validate_publishable_result(payload))
                self.assertEqual(expected, publisher.validate_persisted_result(
                    payload, expected_slug="nvidia-gpu-driver-container",
                    expected_repository="example/project", expected_registration=registration,
                    publication_role="candidate", validation_policy="strict",
                    allow_legacy_missing_decision=False))
                if failure == "no_arm":
                    self.assertEqual("next_regression_failed", payload["tests"]["details"][5]["decision"])
                    self.assertIn("metadata_review_required", payload["tests"]["details"][5]["comparison"])

    def test_collector_records_observed_baseline_failure_and_rejects_contradictory_api(self):
        values = {"steps.test5.outcome": "failure", "steps.test5.outputs.status": "failed"}
        _, regression = self.run_step("test6", values, SCOPED_ARM_PREFLIGHT_PROBE="exit 97")
        values.update({f"steps.test6.outputs.{k}": v for k, v in regression.items()})
        _, summary = self.run_step("summary", values)
        process, payload, registration = self.collect(summary, regression, ["success"] * 4 + ["failure", "success"])
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        self.assertEqual((4, 1, 1), tuple(payload["tests"][k] for k in ("passed", "failed", "skipped")))
        self.assertEqual("failure", publisher.validate_persisted_result(
            payload, expected_slug="nvidia-gpu-driver-container", expected_repository="example/project",
            expected_registration=registration, publication_role="candidate",
            validation_policy="strict", allow_legacy_missing_decision=False))
        process, payload, _ = self.collect(summary, regression, ["success"] * 6)
        self.assertNotEqual(0, process.returncode)
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
