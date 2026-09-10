"""Execute the six CLI workflows' summaries and bounded command contracts."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
SLUGS = ("pcb-rnd", "ringdove-eda", "qrouter", "turbovnc", "xpra", "xschem")
APT_SLUGS = ("pcb-rnd", "ringdove-eda", "xpra", "xschem")


def job(slug):
    workflow = ROOT / ".github/workflows" / f"test-{slug}.yml"
    return next(iter(yaml.safe_load(workflow.read_text())["jobs"].values()))


def step(slug, ident):
    return next(item for item in job(slug)["steps"] if item.get("id") == ident)


def render(script, values):
    def replace(match):
        for part in match[1].split("||"):
            part = part.strip()
            value = part[1:-1] if part.startswith("'") else values.get(part, "")
            if value:
                return value
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, script)


class CliHeadlessWorkflowTests(unittest.TestCase):
    def run_script(self, script, env=None, stubs=None, fixture=None):
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
            environment = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}",
                               GITHUB_OUTPUT=str(output), FIXTURE_ROOT=str(root))
            environment.update(env or {})
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", script],
                                    cwd=root, env=environment, capture_output=True,
                                    text=True, timeout=15)
            fields = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
            return result, fields

    def summary(self, slug, overrides=None):
        values = {}
        for number in range(1, 7):
            values[f"steps.test{number}.outputs.status"] = "passed"
            values[f"steps.test{number}.outcome"] = "success"
            values[f"steps.test{number}.outputs.duration"] = "1"
        values.update(overrides or {})
        return self.run_script(render(step(slug, "summary")["run"], values))

    def test_all_six_successful_outcomes_pass(self):
        for slug in SLUGS:
            with self.subTest(slug=slug):
                result, fields = self.summary(slug)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(fields["passed"], "6")
                self.assertEqual(fields["failed"], "0")
                self.assertEqual(fields["duration"], "6")

    def test_missing_failed_and_skipped_core_outputs_fail_closed(self):
        for slug in SLUGS:
            for status in ("", "failed", "skipped"):
                with self.subTest(slug=slug, status=status):
                    result, fields = self.summary(slug, {"steps.test5.outputs.status": status})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(fields["core_failed"], "1")
                    self.assertEqual(fields["failed"], "1")
                    self.assertEqual(fields["skipped"], "0")

    def test_passed_output_cannot_override_failed_or_cancelled_step(self):
        for slug in SLUGS:
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(slug=slug, outcome=outcome):
                    result, fields = self.summary(slug, {"steps.test5.outcome": outcome})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(fields["overall_status"], "failure")
                    self.assertEqual(fields["badge_status"], "failing")

    def test_only_approved_successful_regression_skip_is_allowed(self):
        for slug in SLUGS:
            approved = "not_applicable_package_manager" if slug in APT_SLUGS else "no_newer_stable_available"
            for decision, outcome, valid in ((approved, "success", True),
                                             (approved, "failure", False),
                                             (approved, "cancelled", False),
                                             ("runtime_validation_not_automated", "success", False),
                                             ("", "success", False)):
                with self.subTest(slug=slug, decision=decision, outcome=outcome):
                    result, fields = self.summary(slug, {
                        "steps.test6.outputs.status": "skipped",
                        "steps.test6.outputs.decision": decision,
                        "steps.test6.outcome": outcome,
                    })
                    self.assertEqual(result.returncode == 0, valid)
                    self.assertEqual(fields["skipped"], "1" if valid else "0")

    def test_regression_pass_cannot_override_failure(self):
        for slug in SLUGS:
            result, fields = self.summary(slug, {"steps.test6.outcome": "failure"})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(fields["failed"], "1")

    def test_core_outputs_are_explicit_before_commands(self):
        for slug in SLUGS:
            for number in range(1, 6):
                script = step(slug, f"test{number}")["run"]
                with self.subTest(slug=slug, test=number):
                    self.assertIn('echo "status=failed" >> "$GITHUB_OUTPUT"', script.splitlines()[:5])
                    self.assertIn('echo "duration=0" >> "$GITHUB_OUTPUT"', script.splitlines()[:6])
                    self.assertIn('echo "status=passed" >> "$GITHUB_OUTPUT"', script)
                    self.assertIn('echo "duration=$((END_TIME - START_TIME))" >> "$GITHUB_OUTPUT"', script)

    def help_smoke(self, slug, help_exit="0", methods="method1", route_exit="0"):
        help_command = 'if [ "$1" = --help ]; then echo "usage help export" >&2; exit "$HELP_EXIT"; fi\necho version\n'
        stubs = {name: help_command for name in ("pcb-rnd", "sch-rnd", "camv-rnd")}
        stubs["dpkg-query"] = 'echo "route-rnd 0.9.2-1 arm64"\n'
        stubs["route-rnd"] = ('case "$1" in --help) echo "Usage: route-rnd";; '
                                '-M) printf "%s" "$METHODS"; exit "$ROUTE_EXIT";; *) exit 1;; esac\n')
        return self.run_script(step(slug, "test5")["run"],
                               {"HELP_EXIT": help_exit, "METHODS": methods, "ROUTE_EXIT": route_exit}, stubs)

    def test_successful_help_on_stderr_is_counted(self):
        for slug in ("pcb-rnd", "ringdove-eda"):
            result, fields = self.help_smoke(slug)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fields["status"], "passed")

    def test_help_error_with_matching_text_still_fails(self):
        for slug in ("pcb-rnd", "ringdove-eda"):
            result, fields = self.help_smoke(slug, help_exit="1")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(fields["status"], "failed")

    def test_route_methods_must_exist_and_command_must_succeed(self):
        for methods, code in (("", "0"), ("method1", "1")):
            result, fields = self.help_smoke("ringdove-eda", methods=methods, route_exit=code)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(fields["status"], "failed")

    def xschem_smoke(self, mode):
        def fixture(root):
            symbols = root / "devices"
            symbols.mkdir()
            (symbols / "res.sym").write_text('v {xschem version=2.8.1 file_version=1.0}\n')
            (symbols / "lab_pin.sym").write_text('v {xschem version=2.8.1 file_version=1.0}\n')
        stubs = {
            "dpkg": 'printf "%s/devices/res.sym\\n" "$FIXTURE_ROOT"\n',
            "xschem": '''while [ "$#" -gt 0 ]; do
  case "$1" in --netlist_path) target="$2"; shift;; esac
  schematic="$1"
  shift
done
grep -Fq 'version=2.8.1 file_version=1.0' "$schematic"
test -d "$target"
case "$MODE" in
  missing) exit 0;;
  wrong) echo 'R1 WRONG OUT 1000' > "$target/smoke.spice";;
  *) echo 'R1 IN OUT 1000' > "$target/smoke.spice";;
esac
if [ "$MODE" = failed ]; then exit 1; fi
''',
        }
        return self.run_script(step("xschem", "test5")["run"], {"MODE": mode}, stubs, fixture)

    def test_xschem_uses_installed_format_and_real_netlist(self):
        result, fields = self.xschem_smoke("valid")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["status"], "passed")

    def test_xschem_missing_wrong_or_failed_netlist_is_not_green(self):
        for mode in ("missing", "wrong", "failed"):
            result, fields = self.xschem_smoke(mode)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertEqual(fields["status"], "failed")

    def test_qrouter_source_and_both_runtime_versions_are_bound(self):
        install = step("qrouter", "install")["run"]
        self.assertIn('sha256sum -c -', install)
        self.assertIn('qrouter-$UPSTREAM_VERSION.tgz', install)
        self.assertNotIn('default_branch', install)
        scripts = (step("qrouter", "test5")["run"],
                   step("qrouter", "test6")["with"]["limited_cpu_probe"])
        self.assertIn('xvfb-run -a qrouter -v0 -h', scripts[0])
        self.assertIn('xvfb-run -a qrouter -noc -s qrouter-smoke.tcl', scripts[0])
        self.assertIn('--with-tcllibs="/usr/lib/$MULTIARCH"', scripts[0])
        self.assertIn('qrouter -nog -v0 -h', scripts[1])
        self.assertIn('qrouter -noc -nog -s qrouter-smoke.tcl', scripts[1])
        for script in scripts:
            self.assertIn('grep -Fx "$EXPECTED_VERSION.T" qrouter-help.txt', script)
            self.assertIn('if {$QROUTER_VERSION ne $expected} {exit 1}', script)
            self.assertNotIn('|| true', script)

    @unittest.skipUnless(shutil.which("tclsh"), "Tcl interpreter is unavailable")
    def test_qrouter_tcl_rejects_a_different_runtime_version(self):
        script = step("qrouter", "test5")["run"]
        tcl = script.split("<<'EOF'\n", 1)[1].split("\nEOF", 1)[0]
        for version, valid in (("1.3", True), ("1.4", False), ("", False)):
            body = ('set env(EXPECTED_VERSION) 1.3.33\n'
                    f'set QROUTER_VERSION "{version}"\n'
                    'proc quit {} {exit 0}\n' + tcl)
            result = subprocess.run([shutil.which("tclsh")], input=body,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_turbovnc_control_fields_are_individually_checked(self):
        script = step("turbovnc", "test5")["run"]
        assertions = script[script.index('test "$(dpkg-deb'):script.index('dpkg-deb -x')]
        stub = '''case "${*: -1}" in
  Architecture) echo "$ARCH";; Package) echo "$PACKAGE";; Version) echo "$VERSION";;
  *) exit 1;; esac
'''
        for arch, package, version, valid in (("arm64", "turbovnc", "3.0-20220503", True),
                                             ("amd64", "turbovnc", "3.0-20220503", False),
                                             ("Architecture: arm64", "turbovnc", "3.0", False),
                                             ("arm64", "other", "3.0", False),
                                             ("arm64", "turbovnc", "3.1", False)):
            result, _ = self.run_script(assertions, {"WORK": "/unused", "BASELINE_VERSION": "3.0",
                                       "ARCH": arch, "PACKAGE": package, "VERSION": version}, {"dpkg-deb": stub})
            self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_servers_keep_live_readiness_and_dynamic_displays(self):
        turbo = step("turbovnc", "test5")["run"]
        xpra = step("xpra", "test5")["run"]
        self.assertIn('-displayfd 3', turbo)
        self.assertIn('-rfbport 0', turbo)
        self.assertIn('xdpyinfo -display', turbo)
        self.assertIn('800x600 pixels', turbo)
        self.assertIn('--displayfd=3', xpra)
        self.assertLess(xpra.index('xpra start'), xpra.index('xpra version ":$DISPLAY_NUM"'))
        for script in (turbo, xpra):
            self.assertIn('test "$READY" = true', script)
            self.assertNotRegex(script, r'(?:-version|xpra info|xdpyinfo).*\|\| true')

    def test_turbovnc_failed_version_command_cannot_pass_on_banner(self):
        script = step("turbovnc", "test5")["run"]
        version = script[script.index('"$XVNC" -version'):script.index('"$XVNC" -displayfd')]
        for code, valid in (("0", True), ("1", False)):
            stub = 'echo "TurboVNC Server (Xvnc) 64-bit v3.0 (build fixture)" >&2\nexit "$VERSION_EXIT"\n'
            result, _ = self.run_script('XVNC="$FIXTURE_ROOT/bin/Xvnc"\n' + version,
                                       {"BASELINE_VERSION": "3.0", "VERSION_EXIT": code}, {"Xvnc": stub})
            self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_xpra_failed_live_query_is_not_a_pass(self):
        stub = '''case "$1" in
  --version) echo 'xpra v3.1.5';;
  start) echo 123 >&3; exec /bin/sleep 10;;
  info) echo 'server version session display'; exit 1;;
  *) exit 1;;
esac
'''
        result, fields = self.run_script(step("xpra", "test5")["run"], stubs={
            "xpra": stub,
            "seq": 'printf "1\\n2\\n"\n',
            "sleep": '/bin/sleep 0.1\n',
            "timeout": 'shift\nexec "$@"\n',
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(fields["status"], "failed")


if __name__ == "__main__":
    unittest.main()
