"""Execute Qflow's summaries and shared native synthesis helper with failures."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-qflow.yml"


def job():
    return next(iter(yaml.safe_load(WORKFLOW.read_text())["jobs"].values()))


def step(ident):
    return next(item for item in job()["steps"] if item.get("id") == ident)


def render(script, values):
    def replace(match):
        for part in match[1].split("||"):
            part = part.strip()
            value = part[1:-1] if part.startswith("'") else values.get(part, "")
            if value:
                return value
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, script)


def runtime_helper():
    return step("toolchain")["run"].split("<<'QFLOW_RUNTIME'\n", 1)[1].split("\nQFLOW_RUNTIME", 1)[0]


class QflowWorkflowTests(unittest.TestCase):
    def run_script(self, script, mode="ok", version="1.1.23", stubs=None, fixture=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "bin"
            binary.mkdir()
            for name, body in (stubs or {}).items():
                path = binary / name
                path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
                path.chmod(0o755)
            if fixture:
                fixture(root)
            output = root / "output"
            output.touch()
            env = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}",
                       GITHUB_OUTPUT=str(output), FIXTURE_ROOT=str(root),
                       FIXTURE_PREFIX=str(root / "install"), MODE=mode,
                       VERSION_FOR_TEST=version, BASELINE_VERSION="1.1.23-1")
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", script],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=20)
            fields = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
            return result, fields

    def summary(self, overrides=None):
        values = {}
        for number in range(1, 7):
            values[f"steps.test{number}.outputs.status"] = "passed"
            values[f"steps.test{number}.outcome"] = "success"
            values[f"steps.test{number}.outputs.duration"] = "1"
        values.update(overrides or {})
        return self.run_script(render(step("summary")["run"], values))

    def test_all_six_successes_count(self):
        result, fields = self.summary()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((fields["passed"], fields["failed"], fields["skipped"], fields["duration"]),
                         ("6", "0", "0", "6"))

    def test_missing_failed_and_skipped_core_outputs_fail_closed(self):
        for number in range(1, 6):
            for status in ("", "failed", "skipped"):
                result, fields = self.summary({f"steps.test{number}.outputs.status": status})
                self.assertNotEqual(result.returncode, 0, (number, status))
                self.assertEqual((fields["core_failed"], fields["failed"], fields["skipped"]), ("1", "1", "0"))

    def test_passing_output_never_overrides_bad_outcome(self):
        for number in range(1, 7):
            for outcome in ("failure", "cancelled", "skipped", ""):
                result, fields = self.summary({f"steps.test{number}.outcome": outcome})
                self.assertNotEqual(result.returncode, 0, (number, outcome))
                self.assertEqual(fields["overall_status"], "failure")

    def test_only_approved_successful_regression_skip_counts(self):
        for decision, outcome, valid in (("no_newer_stable_available", "success", True),
                                         ("no_newer_stable_available", "failure", False),
                                         ("runtime_validation_not_automated", "success", False),
                                         ("not_applicable_package_manager", "success", False)):
            result, fields = self.summary({"steps.test6.outputs.status": "skipped",
                "steps.test6.outputs.decision": decision, "steps.test6.outcome": outcome})
            self.assertEqual(result.returncode == 0, valid)
            self.assertEqual(fields["skipped"], "1" if valid else "0")

    def test_baseline_status_and_duration_are_top_level(self):
        for number in range(1, 6):
            script = step(f"test{number}")["run"]
            self.assertIn('echo "status=failed" >> "$GITHUB_OUTPUT"', script.splitlines()[:5])
            self.assertIn('echo "duration=0" >> "$GITHUB_OUTPUT"', script.splitlines()[:6])
            self.assertIn('echo "status=passed" >> "$GITHUB_OUTPUT"', script)
            self.assertIn('echo "duration=$((END_TIME - START_TIME))" >> "$GITHUB_OUTPUT"', script)

    def test_exact_archive_and_catalog_identity_have_no_fallback(self):
        script = step("install")["run"]
        self.assertIn('https://opencircuitdesign.com/qflow/archive/qflow-$UPSTREAM_VERSION.tgz', script)
        self.assertIn('125127c781512f09937a74d2be0d2384439d54839502e64f27d3369728e8cca4', script)
        self.assertIn('sha256sum -c -', script)
        self.assertNotIn("default_branch", script)
        self.assertNotIn("|| true", script)
        self.assertEqual(job()["env"]["BASELINE_VERSION"], "1.1.23-1")
        for version, valid in (("1.1.23", True), ("1.4.104", False)):
            def fixture(root):
                (root / "baseline-src").mkdir()
                (root / "baseline-src/VERSION").write_text(version + "\n")
            result, fields = self.run_script(step("version")["run"], fixture=fixture)
            self.assertEqual(result.returncode == 0, valid)
            if valid:
                self.assertEqual((fields["version"], fields["upstream_version"]), ("1.1.23-1", "1.1.23"))
            else:
                self.assertNotIn("version", fields)

    def test_bad_archive_digest_stops_before_install_success(self):
        stubs = {"curl": "exit 0\n", "sha256sum": "exit 1\n", "tar": "exit 99\n"}
        result, fields = self.run_script(step("install")["run"], stubs=stubs)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("install_status", fields)

    def test_both_versions_use_same_runtime_and_real_lvs_dependency(self):
        setup = step("toolchain")["run"]
        self.assertIn("20d5ac4595691e995c8c384dc426de1b464e4d89", setup)
        self.assertIn("4942d280bf630cc86616f901e77a10e9f55ace62", setup)
        self.assertIn("command -v netgen-lvs", setup)
        self.assertNotIn("set lvs_tool", setup)
        self.assertNotIn("sed -i", setup)
        self.assertIn('bash "$PWD/qflow-runtime.sh"', step("test5")["run"])
        regression = step("test6")["with"]
        self.assertEqual(regression["next_version_override"], "1.4.104")
        self.assertEqual(regression["candidate_tag_override"], "1.4.104")
        self.assertIn("cbb751b8a6c0f87a4fa0d499facf041e2cafd38c", regression["limited_cpu_probe"])
        self.assertIn('bash "$PWD/qflow-runtime.sh"', regression["limited_cpu_probe"])

    def runtime(self, mode="ok", version="1.1.23"):
        def fixture(root):
            source = root / "source"
            source.mkdir()
            (source / "VERSION").write_text("9.9.9" if mode == "wrong_source" else version)
            configure = source / "configure"
            configure.write_text('#!/bin/bash\nset -euo pipefail\n'
                                 'test "$1" = --build=aarch64-unknown-linux-gnu\n'
                                 'test "$2" = --host=aarch64-unknown-linux-gnu\n'
                                 'test "$MODE" != configure_failure\n')
            configure.chmod(0o755)
            toolchain = root / "toolchain/bin"
            toolchain.mkdir(parents=True)
            netgen = toolchain / "netgen"
            netgen.write_text("#!/bin/bash\nexit 0\n")
            netgen.chmod(0o755)
            if mode == "missing_netgen":
                netgen.unlink()
        stubs = {
            "uname": "echo aarch64\n",
            "cp": "exit 0\n",
            "make": '''test "$MODE" != build_failure
if [ "${1-}" = install ]; then
  mkdir -p "$FIXTURE_PREFIX/bin" "$FIXTURE_PREFIX/share/qflow/bin" "$FIXTURE_PREFIX/share/qflow/tech/osu035"
  /bin/cp "$FIXTURE_ROOT/bin/qflow" "$FIXTURE_PREFIX/bin/qflow"
  echo binary > "$FIXTURE_PREFIX/share/qflow/bin/blif2Verilog"
  if [ "$MODE" != missing_models ]; then echo models > "$FIXTURE_PREFIX/share/qflow/tech/osu035/osu035_stdcells.lib"; fi
fi
''',
            "qflow": '''if [ "$1" = --version ]; then
  test "$MODE" != version_failure
  if [ "$MODE" = wrong_version ]; then echo 'Qflow version 9.9 revision 9'; else
    echo "Qflow version ${VERSION_FOR_TEST%.*} revision ${VERSION_FOR_TEST##*.}"
  fi
  exit 0
fi
test "$*" = '-T osu035 synth and2'
if [ "$MODE" != missing_verilog ]; then echo netlist > synthesis/and2.rtlnopwr.v; fi
if [ "$MODE" != missing_blif ]; then printf '.model and2\\n.gate AND2X2 A=a B=b Y=y\\n.end\\n' > synthesis/and2.blif; fi
if [ "$MODE" != missing_mapped ]; then echo mapped > synthesis/and2_mapped.v; fi
test "$MODE" != synthesis_failure
''',
            "yosys": '''if [[ "$*" == *read_liberty* ]]; then
  test -s "$FIXTURE_PREFIX/share/qflow/tech/osu035/osu035_stdcells.lib"
  for proof in \
    'sat -verify -prove y 0 -set a 0 -set b 0' \
    'sat -verify -prove y 0 -set a 0 -set b 1' \
    'sat -verify -prove y 0 -set a 1 -set b 0' \
    'sat -verify -prove y 1 -set a 1 -set b 1'; do
    [[ "$*" == *"$proof"* ]]
  done
  case "$MODE" in
    model_parse_failure|solver_failure|wrong_00|wrong_01|wrong_10|wrong_11) exit 1;;
    failed_truth_with_success_text) echo 'SUCCESS'; exit 1;;
  esac
  exit 0
fi
test "$MODE" != netlist_parse_failure
python3 - <<'PY'
import json
import os
from pathlib import Path
ports = {"a": {"direction": "input", "bits": [2]}, "b": {"direction": "input", "bits": [3]}, "y": {"direction": "output", "bits": [4]}}
mode = os.environ["MODE"]
if mode == "wrong_ports":
    ports = {}
if mode == "wrong_width":
    ports["a"]["bits"] = [2, 5]
kind = "OR2X2" if mode == "wrong_cell" else "AND2X2"
Path("and2-netlist.json").write_text(json.dumps({"modules": {"and2": {"ports": ports, "cells": {"c": {"type": kind}}}}}))
PY
''',
            "file": 'if [ "$MODE" = wrong_arch ]; then echo "ELF 64-bit x86-64"; else echo "ELF 64-bit ARM aarch64"; fi\n',
            "timeout": 'shift\nexec "$@"\n',
            "sha256sum": "exit 0\n",
        }
        script = ('set -- "$FIXTURE_ROOT/source" "$FIXTURE_PREFIX" "$VERSION_FOR_TEST" '
                  '"$FIXTURE_ROOT/project" "$FIXTURE_ROOT/toolchain"\n' + runtime_helper())
        return self.run_script(script, mode, version, stubs, fixture)

    def test_both_native_runtime_contracts_pass(self):
        for version in ("1.1.23", "1.4.104"):
            result, _ = self.runtime(version=version)
            self.assertEqual(result.returncode, 0, (version, result.stderr))

    def test_configure_build_identity_and_missing_dependency_fail(self):
        for mode in ("configure_failure", "build_failure", "wrong_source", "wrong_version", "version_failure", "wrong_arch", "missing_netgen"):
            result, _ = self.runtime(mode)
            self.assertNotEqual(result.returncode, 0, mode)

    def test_synthesis_and_artifact_failures_never_pass(self):
        for mode in ("synthesis_failure", "missing_verilog", "missing_blif"):
            result, _ = self.runtime(mode)
            self.assertNotEqual(result.returncode, 0, mode)
        result, _ = self.runtime("missing_mapped", "1.4.104")
        self.assertNotEqual(result.returncode, 0)

    def test_actual_netlist_parse_ports_and_mapped_and_cell_are_required(self):
        for mode in ("netlist_parse_failure", "wrong_ports", "wrong_width", "wrong_cell"):
            result, _ = self.runtime(mode)
            self.assertNotEqual(result.returncode, 0, mode)

    def test_all_four_formal_proofs_and_models_must_succeed(self):
        for mode in ("missing_models", "model_parse_failure", "solver_failure", "wrong_00", "wrong_01", "wrong_10", "wrong_11", "failed_truth_with_success_text"):
            result, _ = self.runtime(mode)
            self.assertNotEqual(result.returncode, 0, mode)

    def test_formal_proof_uses_untouched_final_netlist_and_all_input_pairs(self):
        helper = runtime_helper()
        for a, b, expected in ((0, 0, 0), (0, 1, 0), (1, 0, 0), (1, 1, 1)):
            self.assertIn(f"sat -verify -prove y {expected} -set a {a} -set b {b}", helper)
        self.assertEqual(helper.count("sat -verify"), 4)
        self.assertIn("read_liberty $PREFIX/share/qflow/tech/osu035/osu035_stdcells.lib", helper)
        self.assertIn("read_verilog synthesis/and2.rtlnopwr.v", helper)
        self.assertNotIn("write_verilog", helper)

    def test_runtime_failure_keeps_explicit_failed_output(self):
        def fixture(root):
            (root / "qflow-runtime.sh").write_text("exit 1\n")
        script = render(step("test5")["run"], {"steps.version.outputs.upstream_version": "1.1.23"})
        result, fields = self.run_script(script, fixture=fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((fields["status"], fields["duration"]), ("failed", "0"))


if __name__ == "__main__":
    unittest.main()
