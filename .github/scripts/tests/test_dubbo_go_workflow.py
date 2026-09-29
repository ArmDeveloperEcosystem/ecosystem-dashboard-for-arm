"""Exercise Dubbo-go's transport workaround and fail-closed test results."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-dubbo-go.yml"


class DubboGoWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="dubbo-go-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-dubbo-go"]
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.env = dict(os.environ, **job["env"])
        self.env.update(
            GITHUB_OUTPUT=str(self.root / "output"),
            GO_CALLS=str(self.root / "go-calls"),
            TMPDIR=str(self.root),
        )
        self.tools = self.root / "bin"
        self.tools.mkdir()
        self.env["PATH"] = str(self.tools) + os.pathsep + os.environ["PATH"]
        (self.root / "dubbo-go").mkdir()
        self.stub("go", '''
printf '%s\\n' "$*" >> "$GO_CALLS"
test "${GODEBUG:-}" = http2client=0
test "$*" = 'test -run Test -count=1 ./common/... ./protocol/invocation/...'
if [ "${GO_FAILURE:-}" != "" ]; then
  printf '%s\\n' "$GO_FAILURE" >&2
  exit 1
fi
''')
        self.stub("git", '''
test "$1" = clone
test "$2" = --depth
test "$3" = 1
test "$4" = --branch
test "$5" = v3.3.0
test "$6" = https://github.com/apache/dubbo-go.git
if [ "${CLONE_FAIL:-0}" = 1 ]; then exit 1; fi
mkdir -p "$7/protocol"
if [ "${MISSING_MODULE:-0}" != 1 ]; then
  printf 'module dubbo.apache.org/dubbo-go/v3\\n' > "$7/go.mod"
fi
''')

    def stub(self, name: str, body: str) -> None:
        target = self.tools / name
        target.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        target.chmod(0o755)

    def run_step(self, step_id: str, statuses=None, **env: str):
        values = {
            f"steps.{step}.outputs.status": status
            for step, status in (statuses or {}).items()
        }

        def render(text: str) -> str:
            def expression(match: re.Match) -> str:
                key, fallback = match.group(1).split("||")
                return values.get(key.strip(), fallback.strip().strip("'"))

            return re.sub(r"\$\{\{ (.*?) \}\}", expression, text)

        step = self.steps[step_id]
        step_env = {key: render(value) for key, value in step.get("env", {}).items()}
        # The real workflow logs stay private to each fixture, including failures.
        script = render(step["run"]).replace("/tmp/dubbo-go", str(self.root / "dubbo-go"))
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        Path(self.env["GO_CALLS"]).write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", script],
            cwd=self.root, env=dict(self.env, **step_env, **env),
            capture_output=True, text=True, timeout=10,
        )
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def test_both_versions_run_original_scope_with_http1_transport(self) -> None:
        self.assertEqual("v3.1.1", self.env["BASELINE_VERSION"])
        self.assertEqual("v3.3.0", self.env["NEXT_VERSION"])
        for step in ("test5", "test6"):
            with self.subTest(step=step):
                result, outputs = self.run_step(step, statuses={"test5": "passed"})
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("passed", outputs["status"])
                self.assertEqual(1, len(Path(self.env["GO_CALLS"]).read_text().splitlines()))
                if step == "test6":
                    self.assertEqual("v3.3.0", outputs["next_installed_version"])

    def test_go_failures_are_reported_and_never_retried_or_accepted(self) -> None:
        failures = (
            'go: github.com/hashicorp/vault/sdk@v0.7.0: read '
            '"https://proxy.golang.org/github.com/hashicorp/vault/sdk/@v/v0.7.0.mod": '
            'stream error: stream ID 65; INTERNAL_ERROR; received from peer',
            "verifying module: checksum mismatch\nSECURITY ERROR",
            "# dubbo.apache.org/dubbo-go/v3/common\nundefined: missingSymbol",
            "--- FAIL: TestInvocation (0.00s)\nFAIL",
        )
        for step in ("test5", "test6"):
            for failure in failures:
                with self.subTest(step=step, failure=failure):
                    result, outputs = self.run_step(step, GO_FAILURE=failure)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", outputs["status"])
                    self.assertIn(failure, result.stdout + result.stderr)
                    self.assertEqual(1, len(Path(self.env["GO_CALLS"]).read_text().splitlines()))
                    if step == "test6":
                        self.assertEqual("not_installed", outputs["next_installed_version"])
                        self.assertEqual("next_install_failed", outputs["decision"])

    def test_candidate_requires_clone_and_repository_layout(self) -> None:
        for failure in ("CLONE_FAIL", "MISSING_MODULE"):
            with self.subTest(failure=failure):
                result, outputs = self.run_step("test6", **{failure: "1"})
                self.assertNotEqual(0, result.returncode)
                self.assertNotEqual("passed", outputs.get("status"))
                self.assertNotEqual("v3.3.0", outputs.get("next_installed_version"))
                self.assertEqual("", Path(self.env["GO_CALLS"]).read_text())

    def test_candidate_success_reports_actual_baseline_status(self) -> None:
        for baseline in ("passed", "failed", ""):
            with self.subTest(baseline=baseline):
                statuses = {"test5": baseline} if baseline else {}
                result, outputs = self.run_step("test6", statuses=statuses)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(
                    f"baseline v3.1.1 functional validation: {baseline or 'failed'};",
                    outputs["comparison"],
                )
                self.assertEqual("passed", outputs["status"])

    def test_summary_preserves_each_baseline_and_candidate_failure(self) -> None:
        for failed_step in (None, "test1", "test2", "test3", "test4", "test5", "test6", "all"):
            with self.subTest(failed_step=failed_step):
                statuses = {
                    f"test{number}": "failed" if failed_step == f"test{number}" else "passed"
                    for number in range(1, 7)
                } if failed_step != "all" else {}
                result, outputs = self.run_step("summary", statuses=statuses)
                failed = 6 if failed_step == "all" else int(failed_step is not None)
                core_failed = 5 if failed_step == "all" else int(failed_step not in (None, "test6"))
                self.assertEqual(int(failed > 0), result.returncode, result.stderr)
                self.assertEqual(str(failed), outputs["failed"])
                self.assertEqual(str(6 - failed), outputs["passed"])
                self.assertEqual(str(core_failed), outputs["core_failed"])
                self.assertEqual("failure" if failed else "success", outputs["overall_status"])
                self.assertEqual("failing" if core_failed else "passing", outputs["badge_status"])


if __name__ == "__main__":
    unittest.main()
