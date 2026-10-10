"""Exercise the five scoped Arm preflights and their fail-closed summaries."""

import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest
import zipfile
import io

import yaml


ROOT = Path(__file__).resolve().parents[2] / "workflows"
PACKAGES = ("amazon-vpc-cni-k8s", "ampere-ai-text-to-sql", "ampere-optimised-ollama",
            "ampere-optimized-llama", "wsl")


class ArmPreflightPackageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="arm-preflight-tests-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.source = self.root / "baseline-src"
        self.source.mkdir()
        (self.source / "README.md").write_text("Text to SQL\n")
        (self.source / "compose.yaml").write_text(yaml.safe_dump({"services": {"postgres": {
            "image": "ghcr.io/amperecomputingai/ampere-ai-text2sql:pg_dvdrental_0.1",
            "environment": {"POSTGRES_DB": "dvdrental"}}}}))
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        TMPDIR=str(self.root), GITHUB_OUTPUT=str(self.root / "output"),
                        CALLS=str(self.root / "calls"))
        self.stub("uname", 'echo "${ARCH:-aarch64}"')
        self.stub("timeout", 'shift; exec "$@"')
        self.stub("sleep", 'exit 0')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body + "\n")
        path.chmod(0o755)

    def run_step(self, slug, step_id="test5", values=None, **env):
        job = yaml.safe_load((ROOT / f"test-{slug}.yml").read_text())["jobs"][f"test-{slug}"]
        step = next(s for s in job["steps"] if s.get("id") == step_id)
        resolved = {f"steps.test{i}.outcome": "success" for i in range(1, 7)}
        resolved["steps.install.outputs.install_mode"] = "github_source"
        resolved.update(values or {})

        def expression(match):
            parts = match[1].split("||")
            return resolved.get(parts[0].strip()) or (parts[1].strip().strip("'") if len(parts) > 1 else "")

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, step["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **job["env"], **env),
                                text=True, capture_output=True, timeout=15)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def docker_stub(self):
        self.stub("docker", '''
printf '%s\\n' "$*" >> "$CALLS"
if [ "$1" = "${DOCKER_FAIL:-}" ]; then exit 4; fi
case "$1" in
  manifest)
    test "$2" = inspect && test "$3" = --verbose
    printf '%s\\n' "${MANIFEST}" ;;
  image) printf '[{"Architecture":"%s","Os":"linux"}]\\n' "${IMAGE_ARCH:-arm64}" ;;
  run) echo 'Python 3.11.8 / Ollama version 0.1.0' ;;
  exec) echo "${SQL_RESULT:-dvdrental-ok}" ;;
  inspect) echo "${CONTAINER_RUNNING:-true}" ;;
esac
''')
        self.env["MANIFEST"] = json.dumps({"Descriptor": {"platform": {"architecture": "arm64", "os": "linux"}}})

    def test_single_image_manifests_and_actual_commands_pass(self):
        self.docker_stub()
        for slug in ("ampere-ai-text-to-sql", "ampere-optimised-ollama"):
            with self.subTest(slug=slug):
                result, outputs = self.run_step(slug)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("passed", outputs["status"])
        calls = Path(self.env["CALLS"]).read_text()
        self.assertIn("pull --platform linux/arm64", calls)
        self.assertIn("run --rm --name ampere-", calls)
        self.assertIn("run --detach --name ampere-", calls)
        self.assertIn("--network none", calls)
        self.assertIn("rm -f ampere-", calls)
        self.assertNotIn("prune", calls)

    def test_manifest_lists_are_accepted_without_whitespace_assumptions(self):
        self.docker_stub()
        manifest = json.dumps([{"Descriptor": {"platform": {"architecture": "amd64", "os": "linux"}}},
                               {"Descriptor": {"platform": {"architecture": "arm64", "os": "linux"}}}])
        for slug in ("ampere-ai-text-to-sql", "ampere-optimised-ollama"):
            result, outputs = self.run_step(slug, MANIFEST=manifest)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("passed", outputs["status"])

    def test_image_failures_and_wrong_architecture_never_pass(self):
        self.docker_stub()
        failures = [{"ARCH": "x86_64"}, {"MANIFEST": "{}"},
                    {"MANIFEST": '{"platform":{"architecture":"amd64","os":"linux"}}'},
                    {"MANIFEST": '{"platform":{"architecture":"arm64","os":"windows"}}'},
                    {"IMAGE_ARCH": "amd64"}]
        failures += [{"DOCKER_FAIL": command} for command in ("manifest", "pull", "image", "run")]
        for slug in ("ampere-ai-text-to-sql", "ampere-optimised-ollama"):
            for env in failures:
                with self.subTest(slug=slug, env=env):
                    result, outputs = self.run_step(slug, **env)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", outputs["status"])

    def test_text2sql_source_compilation_and_identity_remain_required(self):
        self.docker_stub()
        (self.source / "broken.py").write_text("invalid syntax here!\n")
        result, outputs = self.run_step("ampere-ai-text-to-sql")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        (self.source / "broken.py").unlink()
        (self.source / "README.md").write_text("unrelated product")
        result, outputs = self.run_step("ampere-ai-text-to-sql")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def test_text2sql_database_identity_and_real_query_are_required(self):
        self.docker_stub()
        for env in ({"DOCKER_FAIL": "exec"}, {"SQL_RESULT": "empty"}, {"CONTAINER_RUNNING": "false"}):
            result, outputs = self.run_step("ampere-ai-text-to-sql", **env)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["status"])
        (self.source / "compose.yaml").write_text(yaml.safe_dump({"services": {"postgres": {
            "image": "ghcr.io/amperecomputingai/ampere-ai-text2sql:0.1",
            "environment": {"POSTGRES_DB": "dvdrental"}}}}))
        result, outputs = self.run_step("ampere-ai-text-to-sql")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def cni_stubs(self):
        (self.source / "Gopkg.lock").touch()
        (self.source / "vendor").mkdir()
        (self.source / "main.go").write_text("package main\n")
        (self.source / "cni.yaml").write_text("kind: DaemonSet\n")
        self.stub("go", '''
test "$GOARCH" = arm64 && test "$GOOS" = linux && test "$CGO_ENABLED" = 0
if [ -f go.mod ]; then
  test "$GO111MODULE" = on
else
  test "$GO111MODULE" = off
  test "$PWD" = "$GOPATH/src/github.com/aws/amazon-vpc-cni-k8s"
  test -d vendor
fi
printf '%s\\n' "$*" >> "$CALLS"
test "$1" != "${GO_FAIL:-}"
case "$1" in
  list) echo github.com/aws/amazon-vpc-cni-k8s ;;
  build) test "$2" = -o; touch "$3" ;;
esac
''')
        self.stub("file", 'echo "${BINARY_ARCH:-ELF 64-bit LSB executable, ARM aarch64}"')

    def test_vendored_gopath_and_module_cni_builds(self):
        self.cni_stubs()
        for module in (False, True):
            with self.subTest(module=module):
                if module:
                    (self.source / "go.mod").write_text("module github.com/aws/amazon-vpc-cni-k8s\n")
                result, outputs = self.run_step("amazon-vpc-cni-k8s")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("passed", outputs["status"])
        self.assertIn("build -o", Path(self.env["CALLS"]).read_text())

    def test_cni_build_architecture_and_manifest_failures_are_fatal(self):
        self.cni_stubs()
        for env in ({"GO_FAIL": "list"}, {"GO_FAIL": "build"}, {"BINARY_ARCH": "ELF x86-64"}):
            with self.subTest(env=env):
                result, outputs = self.run_step("amazon-vpc-cni-k8s", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])
        (self.source / "cni.yaml").write_text("unrelated: data\n")
        result, outputs = self.run_step("amazon-vpc-cni-k8s")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def wsl_fixture(self, architecture="arm64", machine=0xAA64, kernel=True, version="2.0.0.0", nested_msi=False):
        self.env["WSL_RELEASE"] = str(self.root / "release.json")
        self.env["WSL_BUNDLE"] = str(self.root / "bundle")
        Path(self.env["WSL_RELEASE"]).write_text(json.dumps({"tag_name": "2.0.0", "assets": [
            {"name": "wsl.2.0.0.0.x64.msi", "browser_download_url": "https://example.invalid/wrong"},
            {"name": "Microsoft.WSL_2.0.0.0_x64_ARM64.msixbundle", "browser_download_url": "https://example.invalid/bundle"}]}))
        binary = bytearray(70)
        binary[:2] = b"MZ"
        struct.pack_into("<I", binary, 60, 64)
        binary[64:68] = b"PE\0\0"
        struct.pack_into("<H", binary, 68, machine)
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as arm:
            arm.writestr("AppxManifest.xml", f'<Package><Identity ProcessorArchitecture="{architecture}" Version="{version}" /></Package>')
            arm.writestr("wsl.exe", binary)
            if nested_msi:
                arm.writestr("wsl.msi", b"fixture MSI input for stub extractor")
            elif kernel:
                arm.writestr("tools\\kernel", b"kernel")
        with zipfile.ZipFile(self.env["WSL_BUNDLE"], "w") as outer:
            outer.writestr("AppxMetadata/AppxBundleManifest.xml", '<Bundle><Packages><Package Type="application" Architecture="arm64" FileName="arm.msix"/></Packages></Bundle>')
            outer.writestr("arm.msix", nested.getvalue())
        self.stub("curl", '''
SOURCE="$WSL_BUNDLE"
for argument in "$@"; do
  case "$argument" in
    *releases/tags/*) SOURCE="$WSL_RELEASE" ;;
    *example.invalid/wrong*) exit 99 ;;
  esac
done
while [ "$1" != -o ]; do shift; done
cp "$SOURCE" "$2"
''')

    def test_wsl_exact_bundle_nested_arm_manifest_and_pe_payload(self):
        self.wsl_fixture()
        result, outputs = self.run_step("wsl")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertIn("2.0.0.0", result.stdout)

    def test_wsl_nested_msi_kernel_extraction_is_required(self):
        self.wsl_fixture(nested_msi=True)
        self.stub("msiextract", '''
test "$1" = --directory
test -s "$3"
test "${MSI_FAIL:-0}" = 0
mkdir -p "$2/WSL/tools"
if [ "${MSI_KERNEL:-yes}" = yes ]; then printf kernel > "$2/WSL/tools/kernel"; fi
''')
        result, outputs = self.run_step("wsl")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        for env in ({"MSI_FAIL": "1"}, {"MSI_KERNEL": "no"}):
            result, outputs = self.run_step("wsl", **env)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["status"])

    def test_wsl_wrong_architecture_version_and_missing_payload_fail(self):
        for values in ({"architecture": "x64"}, {"machine": 0x8664},
                       {"kernel": False}, {"version": "2.1.0.0"}):
            with self.subTest(values=values):
                self.wsl_fixture(**values)
                result, outputs = self.run_step("wsl")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])

    def test_wsl_non_zip_and_wrong_release_are_not_accepted(self):
        self.wsl_fixture()
        Path(self.env["WSL_BUNDLE"]).write_bytes(b"not a zip")
        result, outputs = self.run_step("wsl")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        Path(self.env["WSL_RELEASE"]).write_text('{"tag_name":"9.0.0","assets":[]}')
        result, outputs = self.run_step("wsl")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def test_summaries_reject_empty_skipped_failed_core_outputs(self):
        for slug in PACKAGES:
            for number in range(1, 7):
                for status in ("", "skipped", "failed"):
                    with self.subTest(slug=slug, number=number, status=status):
                        values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
                        values[f"steps.test{number}.outputs.status"] = status
                        result, outputs = self.run_step(slug, "summary", values)
                        self.assertNotEqual(0, result.returncode)
                        self.assertEqual("1", outputs["failed"])
                        self.assertEqual(str(int(number < 6)), outputs["core_failed"])
                        self.assertEqual("failure", outputs["overall_status"])

    def test_passed_output_requires_actual_success_outcome(self):
        for slug in PACKAGES:
            for number in range(1, 7):
                for outcome in ("", "failure", "cancelled", "skipped"):
                    with self.subTest(slug=slug, number=number, outcome=outcome):
                        values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
                        values[f"steps.test{number}.outcome"] = outcome
                        result, outputs = self.run_step(slug, "summary", values)
                        self.assertNotEqual(0, result.returncode)
                        self.assertEqual("1", outputs["failed"])
                        self.assertEqual("5", outputs["passed"])

    def test_approved_regression_skip_requires_successful_outcome(self):
        for slug in PACKAGES:
            for outcome in ("success", "failure", "cancelled", ""):
                with self.subTest(slug=slug, outcome=outcome):
                    values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)}
                    values.update({"steps.test6.outputs.status": "skipped", "steps.test6.outcome": outcome,
                                   "steps.test6.outputs.decision": "no_newer_stable_available"})
                    result, outputs = self.run_step(slug, "summary", values)
                    self.assertEqual(int(outcome != "success"), result.returncode)
                    self.assertEqual(str(int(outcome == "success")), outputs["skipped"])

    def test_six_explicit_successes_pass_and_baseline_versions_are_unchanged(self):
        expected = dict(zip(PACKAGES, ("1.4.0", "0.1", "1.0.0-ol9", "1.2.0", "2.0.0")))
        for slug in PACKAGES:
            values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
            result, outputs = self.run_step(slug, "summary", values)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("6", outputs["passed"])
            job = yaml.safe_load((ROOT / f"test-{slug}.yml").read_text())["jobs"][f"test-{slug}"]
            self.assertEqual(expected[slug], job["env"]["BASELINE_VERSION"])

    def test_llama_unresolved_or_unbuildable_pinned_source_fails_explicitly(self):
        self.stub("sudo", 'echo unexpected-build-command >&2; exit 99')
        for tag in ("default_branch", "v1.2.2", "v1.2.0"):
            with self.subTest(tag=tag):
                result, outputs = self.run_step("ampere-optimized-llama", values={
                    "steps.install.outputs.resolved_tag": tag})
                self.assertEqual(1, result.returncode)
                self.assertEqual("failed", outputs["status"])
                self.assertNotIn("unexpected-build-command", result.stderr)
                self.assertIn("source", outputs["note"])


if __name__ == "__main__":
    unittest.main()
