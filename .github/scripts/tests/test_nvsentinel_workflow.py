"""Exercise NVSentinel's chart selection and fail-closed summary."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-nvsentinel.yml"


class NVSentinelWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nvsentinel-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-nvsentinel"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        for source in ("baseline-src", "next-src"):
            chart = self.root / source / "distros/kubernetes/nvsentinel"
            chart.mkdir(parents=True)
            (chart / "Chart.yaml").write_text("name: nvsentinel\n")
            nested = chart / "charts/incluster-file-server"
            nested.mkdir(parents=True)
            (nested / "Chart.yaml").write_text("name: incluster-file-server\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        helm = self.bin / "helm"
        helm.write_text('''#!/bin/bash
set -euo pipefail
printf '%s\\n' "$*" >> "$CALLS"
test "$1" = template
test "$3" = distros/kubernetes/nvsentinel
test "$4" = --include-crds
test "${HELM_FAIL:-0}" = 0
printf '%s\\n' "${MANIFEST:-kind: DaemonSet}"
''')
        helm.chmod(0o755)
        self.environment = dict(
            os.environ, **self.job["env"],
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            GITHUB_OUTPUT=str(self.root / "output"), CALLS=str(self.root / "calls"),
        )

    def run_step(self, step_id, values=None, **environment):
        step = self.steps[step_id]
        source = step.get("run") or step["with"]["limited_cpu_probe"]
        resolved = {"steps.install.outputs.install_mode": "github_source"}
        resolved.update(values or {})

        def expression(match):
            parts = match[1].split("||")
            return resolved.get(parts[0].strip()) or parts[-1].strip().strip("'")

        source = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)
        source = source.replace("/tmp/nvsentinel-", str(self.root / "nvsentinel-"))
        output = Path(self.environment["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", source], cwd=self.root,
            env=dict(self.environment, **environment), capture_output=True, text=True,
            timeout=15,
        )
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def test_both_versions_render_the_umbrella_chart(self):
        for step_id in ("test5", "test6"):
            with self.subTest(step=step_id):
                result, outputs = self.run_step(step_id)
                self.assertEqual(0, result.returncode, result.stderr)
                if step_id == "test5":
                    self.assertEqual("passed", outputs["status"])
        calls = (self.root / "calls").read_text()
        self.assertEqual(2, calls.count("distros/kubernetes/nvsentinel --include-crds"))
        self.assertNotIn("dependency build", calls)
        self.assertNotIn("--set", calls)

    def test_missing_parent_chart_cannot_fall_back_to_a_subchart(self):
        for step_id, source in (("test5", "baseline-src"), ("test6", "next-src")):
            with self.subTest(step=step_id):
                (self.root / source / "distros/kubernetes/nvsentinel/Chart.yaml").unlink()
                result, outputs = self.run_step(step_id)
                self.assertNotEqual(0, result.returncode)
                if step_id == "test5":
                    self.assertEqual("failed", outputs["status"])

    def test_render_errors_and_amd64_only_manifests_fail(self):
        cases = ({"HELM_FAIL": "1"}, {"MANIFEST": "unrelated: data"},
                 {"MANIFEST": "kind: DaemonSet\nnodeSelector:\n  kubernetes.io/arch: amd64"})
        for step_id in ("test5", "test6"):
            for environment in cases:
                with self.subTest(step=step_id, environment=environment):
                    result, outputs = self.run_step(step_id, **environment)
                    self.assertNotEqual(0, result.returncode)
                    if step_id == "test5":
                        self.assertEqual("failed", outputs["status"])
                        self.assertIn("duration", outputs)

    def test_summary_requires_all_six_tests_to_pass(self):
        statuses = {f"steps.test{index}.outputs.status": "passed" for index in range(1, 7)}
        result, outputs = self.run_step("summary", statuses)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", outputs["passed"])
        self.assertEqual("success", outputs["overall_status"])
        for index in range(1, 7):
            for status in ("failed", "", "skipped"):
                with self.subTest(index=index, status=status):
                    values = dict(statuses, **{f"steps.test{index}.outputs.status": status})
                    result, outputs = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failure", outputs["overall_status"])
                    self.assertEqual("failing", outputs["badge_status"])


if __name__ == "__main__":
    unittest.main()
