"""Execute FigTree's workflow scripts with fixtures, not an Arm runtime claim."""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-figtree.yml"


class FigTreeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="figtree-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-figtree"]
        self.steps = {step.get("id", step["name"]): step for step in self.job["steps"]}
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        RUNNER_TEMP=str(self.root), FIXTURE_ROOT=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"))
        self.values = {"steps.version.outputs.version": "1.4.4-6"}
        for number in range(1, 7):
            self.values[f"steps.test{number}.outputs.status"] = "passed"
            self.values[f"steps.test{number}.outcome"] = "success"
            self.values[f"steps.test{number}.outputs.duration"] = str(number)
        self.values.update({
            "steps.test6.outputs.status": "skipped",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outputs.duration": "0",
        })
        self.tool("python3", f"exec {shlex.quote(sys.executable)} -B \"$@\"\n")
        # Execute the wrapped command, and fail if the workflow drops its bounds.
        self.tool("timeout", '''test "$1" = --kill-after=5s
case "$2:$3" in 60s:xvfb-run|15s:java) ;; *) exit 90;; esac
shift 2
exec "$@"
''')
        self.tool("xvfb-run", '''test "$1" = -a && test "$2" = -s
test "$3" = '-screen 0 1024x768x24 -nolisten tcp'
shift 3
test "$1" = figtree
if [ "${XVFB_RC:-0}" != 0 ]; then echo 'Xvfb startup failed' >&2; exit "$XVFB_RC"; fi
export FIXTURE_DISPLAY=1
exec "$@"
''')
        self.tool("figtree", '''import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

assert os.environ.get("FIXTURE_DISPLAY") == "1", "export must run under Xvfb"
assert sys.argv[1:7] == ["-graphic", "SVG", "-width", "640", "-height", "480"]
assert len(sys.argv) == 9
source, target = map(Path, sys.argv[7:])
assert source.read_text() == "((Alpha:0.1,Beta:0.2):0.3,Gamma:0.4);\\n"
assert source.parent == target.parent
assert not target.exists(), "render must not reuse stale evidence"
(Path(os.environ["FIXTURE_ROOT"]) / "invocation.json").write_text(json.dumps(sys.argv[1:]))
print("FigTree fixture stdout: loading tree")
print("FigTree fixture stderr: diagnostic", file=sys.stderr)
mode = os.environ.get("SVG_MODE", "valid")
root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width="640.0", height="480.0")
for label in ("Alpha", "Beta", "Gamma"):
    if mode == "missing_label" and label == "Gamma":
        continue
    element = ET.SubElement(root, "desc" if mode == "description_only" else "text")
    ET.SubElement(element, "tspan").text = label
if mode != "no_geometry":
    if mode == "line_geometry":
        ET.SubElement(root, "line", x1="10", x2="100", y1="20", y2="20")
    else:
        ET.SubElement(root, "path", d="" if mode == "empty_path" else "M10 20 L100 20")
if mode == "wrong_size":
    root.set("width", "1")
if mode == "wrong_namespace":
    root.set("xmlns", "urn:not-svg")
if mode == "malformed":
    target.write_text("<svg")
elif mode == "empty":
    target.touch()
elif mode != "missing":
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
sys.exit(int(os.environ.get("EXPORT_RC", "0")))
''', python=True)

    def tool(self, name, body, python=False):
        path = self.bin / name
        header = f"#!{sys.executable} -B\n" if python else "#!/bin/bash\nset -euo pipefail\n"
        path.write_text(header + body)
        path.chmod(0o755)
        return path

    def render(self, script):
        def replace(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term[1:-1]
                value = self.values.get(term, "")
                if value:
                    return value
                if term.isdigit():
                    return term
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, script)

    def run_step(self, name, **env):
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.render(self.steps[name]["run"])],
            cwd=self.root, env=dict(self.env, **env), capture_output=True, text=True, timeout=15,
        )
        fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, fields

    def assert_render_failure(self, result, fields):
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", fields["status"])
        self.assertRegex(fields["duration"], r"^\d+$")
        self.assertNotIn("status=passed", Path(self.env["GITHUB_OUTPUT"]).read_text())
        self.assertIn(f"FigTree render check exit code: {result.returncode}", result.stdout)

    def test_success_executes_bounded_export_and_real_svg_validator(self):
        for mode in ("valid", "line_geometry"):
            with self.subTest(mode=mode):
                result, fields = self.run_step("test4", SVG_MODE=mode)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("passed", fields["status"])
                self.assertEqual("0", fields["exit_code"])
                self.assertIn("Verified 640x480 SVG with Alpha, Beta, Gamma", result.stdout)
                evidence = Path(fields["evidence_dir"])
                self.assertTrue((evidence / "tree.svg").is_file())
                self.assertEqual("0\n", (evidence / "exit-code.txt").read_text())
                self.assertIn("fixture stderr", (evidence / "export.log").read_text())
                invocation = json.loads((self.root / "invocation.json").read_text())
                self.assertEqual([str(evidence / "tree.nwk"), str(evidence / "tree.svg")], invocation[-2:])

    def test_nonzero_and_timeout_cannot_pass_even_with_valid_svg(self):
        # Reproduces the old non-timeout failure branch and its separate timeout false pass.
        for code in (1, 2, 42, 124, 126, 127, 137):
            with self.subTest(code=code):
                result, fields = self.run_step("test4", EXPORT_RC=str(code))
                self.assert_render_failure(result, fields)
                self.assertEqual(code, result.returncode)
                self.assertEqual(str(code), fields["exit_code"])
                self.assertIn(f"FigTree SVG export exit code: {code}", result.stdout)
                self.assertIn("fixture stdout", result.stdout)
                self.assertIn("fixture stderr", result.stdout)
                evidence = Path(fields["evidence_dir"])
                self.assertTrue((evidence / "tree.svg").is_file())
                self.assertEqual(f"{code}\n", (evidence / "exit-code.txt").read_text())
                self.assertNotIn("Verified 640x480", result.stdout)

    def test_zero_exit_requires_load_and_render_evidence(self):
        for mode in ("missing", "empty", "malformed", "wrong_namespace", "wrong_size",
                     "missing_label", "description_only", "no_geometry", "empty_path"):
            with self.subTest(mode=mode):
                result, fields = self.run_step("test4", SVG_MODE=mode)
                self.assert_render_failure(result, fields)
                self.assertEqual("0", fields["exit_code"])
                self.assertTrue((self.root / "invocation.json").is_file())

    def test_success_then_no_output_does_not_reuse_previous_svg(self):
        first, previous = self.run_step("test4")
        self.assertEqual(0, first.returncode, first.stderr)
        result, fields = self.run_step("test4", SVG_MODE="missing")
        self.assert_render_failure(result, fields)
        self.assertNotEqual(previous["evidence_dir"], fields["evidence_dir"])

    def test_xvfb_startup_failure_is_visible_and_cannot_pass(self):
        result, fields = self.run_step("test4", XVFB_RC="3")
        self.assert_render_failure(result, fields)
        self.assertEqual(3, result.returncode)
        self.assertEqual("3", fields["exit_code"])
        self.assertIn("Xvfb startup failed", result.stdout)
        self.assertFalse((self.root / "invocation.json").exists())

    def test_java_producer_exit_and_complete_output_are_preserved(self):
        self.tool("java", '''test "$1" = -version
printf 'openjdk version fixture\\nsecond diagnostic line\\n' >&2
exit "${JAVA_RC:-0}"
''')
        for code in (0, 7, 124):
            with self.subTest(code=code):
                result, fields = self.run_step("test3", JAVA_RC=str(code))
                self.assertEqual(code, result.returncode, result.stderr)
                self.assertEqual("passed" if code == 0 else "failed", fields["status"])
                self.assertEqual(str(code), fields["exit_code"])
                self.assertIn("second diagnostic line", result.stdout)
                self.assertIn(f"Java version exit code: {code}", result.stdout)

    def test_launcher_check_still_requires_arm64(self):
        self.tool("figtree", 'exec java -jar /usr/share/java/figtree.jar "$@"\n')
        self.tool("uname", 'printf "%s\\n" "$FIXTURE_ARCH"\n')
        for arch, expected in (("aarch64", "passed"), ("x86_64", "failed")):
            result, fields = self.run_step("test5", FIXTURE_ARCH=arch)
            self.assertEqual(expected, fields["status"])
            self.assertEqual(arch == "aarch64", result.returncode == 0)
            if arch != "aarch64":
                self.assertNotIn("status=passed", Path(self.env["GITHUB_OUTPUT"]).read_text())

    def test_summary_uses_actual_package_manager_step_and_five_core_tests(self):
        result, fields = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("not_applicable_package_manager", fields["decision"])
        self.assertEqual("1.4.4-6", fields["current_version"])
        self.values.update({f"steps.test6.outputs.{key}": value for key, value in fields.items()})
        result, fields = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1", "0", "15", "success", "passing"),
                         tuple(fields[key] for key in ("passed", "failed", "skipped", "core_failed",
                                                       "duration", "overall_status", "badge_status")))

    def test_every_core_requires_passed_status_and_raw_success(self):
        for number in range(1, 6):
            for status, outcome in (("", "success"), ("skipped", "success"), ("failed", "success"),
                                    ("passed", "failure"), ("passed", "cancelled"),
                                    ("passed", "skipped"), ("passed", "")):
                with self.subTest(number=number, status=status, outcome=outcome):
                    self.values[f"steps.test{number}.outputs.status"] = status
                    self.values[f"steps.test{number}.outcome"] = outcome
                    result, fields = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("4", "1", "1", "1", "failure", "failing"),
                                     tuple(fields[key] for key in ("passed", "failed", "skipped",
                                                                   "core_failed", "overall_status", "badge_status")))
            self.values[f"steps.test{number}.outputs.status"] = "passed"
            self.values[f"steps.test{number}.outcome"] = "success"

    def test_failed_render_reaches_failed_summary_with_pm_skip(self):
        result, fields = self.run_step("test4", EXPORT_RC="42")
        self.assert_render_failure(result, fields)
        self.values.update({f"steps.test4.outputs.{key}": value for key, value in fields.items()})
        self.values["steps.test4.outcome"] = "failure"
        result, fields = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("4", "1", "1", "1"),
                         tuple(fields[key] for key in ("passed", "failed", "skipped", "core_failed")))

    def test_pm_skip_requires_exact_status_decision_and_successful_outcome(self):
        for status, decision, outcome in (
            ("passed", "not_applicable_package_manager", "success"),
            ("skipped", "not_configured", "success"),
            ("skipped", "", "success"),
            ("skipped", "not_applicable_package_manager", "failure"),
            ("skipped", "not_applicable_package_manager", "cancelled"),
            ("skipped", "not_applicable_package_manager", "skipped"),
            ("skipped", "not_applicable_package_manager", ""),
            ("", "not_applicable_package_manager", "success"),
        ):
            with self.subTest(status=status, decision=decision, outcome=outcome):
                self.values["steps.test6.outputs.status"] = status
                self.values["steps.test6.outputs.decision"] = decision
                self.values["steps.test6.outcome"] = outcome
                result, fields = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("5", "1", "0", "0", "failure", "failing"),
                                 tuple(fields[key] for key in ("passed", "failed", "skipped",
                                                               "core_failed", "overall_status", "badge_status")))

    def test_missing_results_fail_closed(self):
        self.values.clear()
        result, fields = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("0", "6", "0", "5"),
                         tuple(fields[key] for key in ("passed", "failed", "skipped", "core_failed")))

    def test_apt_free_arm_and_evidence_contract_remain_explicit(self):
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertLessEqual(self.job["timeout-minutes"], 15)
        self.assertIn("apt-get install -y figtree default-jre xvfb xauth python3", self.steps["install"]["run"])
        self.assertEqual([f"test{n}" for n in range(1, 7)],
                         [name for name in self.steps if re.fullmatch(r"test\d+", name)])
        self.assertEqual("always()", self.steps["summary"]["if"])
        self.assertIn('cat "$SMOKE_DIR/export.log"', self.steps["test4"]["run"])
        self.assertIn('echo "FigTree SVG export exit code: $EXPORT_RC"', self.steps["test4"]["run"])
        self.assertEqual(
            ["actions/checkout@11d5960a326750d5838078e36cf38b85af677262"],
            [step["uses"] for step in self.job["steps"] if "uses" in step],
        )
        for number in range(1, 6):
            script = self.steps[f"test{number}"]["run"]
            self.assertIn('echo "status=failed" >> "$GITHUB_OUTPUT"', script.splitlines()[:3])


if __name__ == "__main__":
    unittest.main()
