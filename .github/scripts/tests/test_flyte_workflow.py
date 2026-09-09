"""Keep Flyte's transport workaround separate from its real test outcomes."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]


class FlyteWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="flyte-workflow-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        job = yaml.safe_load((ROOT / ".github/workflows/test-flyte.yml").read_text())["jobs"]["test-flyte"]
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.env = dict(os.environ, **job["env"], GITHUB_OUTPUT=str(self.root / "output"))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin) + os.pathsep + os.environ["PATH"]
        (self.root / "baseline-src").mkdir()
        self.stub("setup-envtest", 'printf "%s\\n" "$ENVTEST_ASSETS"\n')
        self.env["ENVTEST_STUB"] = str(self.bin / "setup-envtest")
        self.env["ENVTEST_ASSETS"] = str(self.root / "envtest-assets")
        self.stub("go", '''
test "$GODEBUG" = http2client=0
printf '%s\\n' "$*" >> "$CALLS"
if [ "$1" = "$FAIL_STAGE" ]; then
  printf '%s\\n' "$FAILURE" >&2
  exit 1
fi
if [ "$1" = list ] && [ "${2:-}" = -m ]; then
  case "${@: -1}" in
    sigs.k8s.io/controller-runtime) echo v0.24.1 ;;
    k8s.io/api) echo v0.37.0 ;;
    *) exit 1 ;;
  esac
elif [ "$1" = install ]; then
  cp "$ENVTEST_STUB" "$GOBIN/setup-envtest"
fi
''')
        self.stub("mktemp", 'mkdir -p "$ENVTEST_TEMP"\nprintf "%s\\n" "$ENVTEST_TEMP"\n')
        self.env["ENVTEST_TEMP"] = str(self.root / "envtest")

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def run_step(self, step_id, values=None, **environment):
        values = {"steps.install.outputs.install_mode": "github_source", **(values or {})}
        def expression(match):
            terms = match[1].split("||")
            return values.get(terms[0].strip(), terms[-1].strip().strip("'") if len(terms) > 1 else "")
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step_id]["run"])
        script = script.replace("/tmp/flyte", str(self.root / "flyte"))
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
            env=dict(self.env, CALLS=str(self.root / "calls"), **environment),
            capture_output=True, text=True, timeout=10,
        )
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def successful_statuses(self):
        return {f"steps.test{i}.{key}": value for i in range(1, 7)
                for key, value in (("outputs.status", "passed"), ("outcome", "success"))}

    def test_transport_workaround_does_not_change_go_validation_scope(self):
        self.assertEqual("http2client=0", self.env["GODEBUG"])
        self.assertEqual("0.8.19", self.env["BASELINE_VERSION"])
        self.assertIn("GOOS=linux GOARCH=arm64 go test -run '^$' ./...", self.steps["test5"]["run"])
        self.assertIn('go test -run \'^$\' "${FLYTE_SMOKE_PKGS[@]}"', self.steps["test6"]["with"]["limited_cpu_probe"])
        self.assertIn("head -n 40", self.steps["test6"]["with"]["limited_cpu_probe"])
        self.assertEqual("false", self.steps["test6"]["with"]["defer_on_limited_cpu_probe_failure"])
        self.assertNotIn("GOSUMDB", self.env)
        self.assertNotIn("GOINSECURE", self.env)

    def source_identity_fixture(self):
        page = self.root / self.env["PACKAGE_PAGE"]
        page.parent.mkdir(parents=True)
        page.write_text("version_number: 0.8.19\n")
        self.stub("git", '''
case "${@: -1}" in
  HEAD) test -n "$SOURCE_COMMIT"; printf '%s\\n' "$SOURCE_COMMIT" ;;
  refs/tags/*) test -n "$TAG_COMMIT"; printf '%s\\n' "$TAG_COMMIT" ;;
  *) exit 1 ;;
esac
''')

    def test_default_branch_wrong_version_and_metadata_only_are_not_baselines(self):
        self.source_identity_fixture()
        for resolved in ("default_branch", "v2.0.48", ""):
            with self.subTest(resolved=resolved):
                result, outputs = self.run_step("test2", {
                    "steps.install.outputs.resolved_tag": resolved,
                }, SOURCE_COMMIT="observed-default-commit", TAG_COMMIT="observed-default-commit")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])
                self.assertEqual("observed-default-commit", outputs["source_commit"])
                self.assertIn("cannot certify", outputs["note"])
        result, outputs = self.run_step("test2", {
            "steps.install.outputs.install_mode": "external_artifact",
        })
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def test_baseline_tag_must_identify_actual_checkout(self):
        self.source_identity_fixture()
        for resolved in ("0.8.19", "v0.8.19"):
            for source, tag in (("source-a", "source-a"), ("source-a", "source-b"), ("source-a", ""), ("", "source-a")):
                with self.subTest(resolved=resolved, source=source, tag=tag):
                    result, outputs = self.run_step("test2", {
                        "steps.install.outputs.resolved_tag": resolved,
                    }, SOURCE_COMMIT=source, TAG_COMMIT=tag)
                    valid = bool(source) and source == tag
                    self.assertEqual(valid, result.returncode == 0, result.stderr)
                    self.assertEqual("passed" if valid else "failed", outputs["status"])

    def test_fetch_checksum_and_compile_errors_remain_failures(self):
        for stage in ("list", "test"):
            for message in ("stream error: INTERNAL_ERROR", "checksum mismatch", "undefined: missingSymbol"):
                with self.subTest(stage=stage, message=message):
                    result, outputs = self.run_step("test5", FAIL_STAGE=stage, FAILURE=message)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn(message, result.stdout + result.stderr)
                    self.assertEqual("failed", outputs["status"])
                    self.assertIn("duration", outputs)

    def test_envtest_install_and_asset_failures_remain_failures(self):
        result, outputs = self.run_step("test5", FAIL_STAGE="install", FAILURE="envtest install failed")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("envtest install failed", result.stderr)
        self.assertEqual("failed", outputs["status"])
        calls = (self.root / "calls").read_text()
        self.assertIn("install sigs.k8s.io/controller-runtime/tools/setup-envtest@release-0.24", calls)
        self.stub("setup-envtest", '''
test "$*" = "use 1.37 --bin-dir $ENVTEST_TEMP/assets -p path"
echo 'envtest asset checksum mismatch' >&2
exit 1
''')
        result, outputs = self.run_step("test5", FAIL_STAGE="", FAILURE="")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("envtest asset checksum mismatch", result.stderr)
        self.assertEqual("failed", outputs["status"])
        self.assertIn("duration", outputs)

    def test_candidate_fetch_and_compile_failures_preserve_package_scope(self):
        if subprocess.run(["bash", "-c", "(( BASH_VERSINFO[0] >= 4 ))"]).returncode:
            self.skipTest("Candidate mapfile requires the runner's Bash 4 or newer")
        (self.root / "next-src").mkdir()
        self.steps["candidate"] = {
            "run": "set -euo pipefail\n" + self.steps["test6"]["with"]["limited_cpu_probe"]
        }
        self.stub("go", '''
test "$GODEBUG" = http2client=0
printf '%s\\n' "$*" >> "$CALLS"
if [ "$1" = "$FAIL_STAGE" ]; then
  printf '%s\\n' "$FAILURE" >&2
  exit 1
fi
if [ "$1" = list ]; then
  printf '%s\\n' github.com/flyteorg/flyte/v2/flytestdlib/integration/fixture
  printf '%s\\n' github.com/flyteorg/flyte/v2/flyteadmin/fixture
  for ((i=1; i<=45; i++)); do
    printf 'github.com/flyteorg/flyte/v2/flytestdlib/fixture%s\\n' "$i"
  done
fi
''')
        for stage in ("list", "test"):
            for message in ("stream error: INTERNAL_ERROR", "checksum mismatch", "undefined: missingSymbol"):
                with self.subTest(stage=stage, message=message):
                    calls = self.root / "calls"
                    calls.write_text("")
                    result, _ = self.run_step("candidate", FAIL_STAGE=stage, FAILURE=message)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn(message, result.stdout + result.stderr)
                    commands = calls.read_text().splitlines()
                    self.assertEqual("list ./...", commands[0])
                    if stage == "test":
                        arguments = commands[1].split()
                        self.assertEqual(["test", "-run", "^$"], arguments[:3])
                        self.assertEqual([
                            f"github.com/flyteorg/flyte/v2/flytestdlib/fixture{i}"
                            for i in range(1, 41)
                        ], arguments[3:])

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
