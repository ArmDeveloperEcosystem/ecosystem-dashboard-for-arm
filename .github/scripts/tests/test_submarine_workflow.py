"""Execute Submarine's u-root setup and build boundary with controlled failures."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-submarine.yml"
DOWNLOAD_ERROR = (
    '/github/home/go/pkg/mod/github.com/u-root/mkuimage@'
    'v0.0.0-20240225063926-11a3bcc79c2a/uimage/templates/templates.go:16:2: '
    'unrecognized import path "gopkg.in/yaml.v3": '
    'reading https://gopkg.in/yaml.v3?go-get=1: 502 Proxy Error'
)


class SubmarineWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="submarine-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-submarine"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()
        self.env = dict(os.environ, **self.job["env"])
        self.env.update(
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            TMPDIR=str(self.tmp),
            FIXTURE_ROOT=str(self.root),
            BASE_DIR=str(self.root / "current"),
            NEXT_DIR=str(self.root / "regression"),
            CURRENT="0.4.0",
            LATEST="0.5.1",
            START_TIME="0",
            GITHUB_OUTPUT=str(self.root / "output"),
        )
        self.stub("go", f"#!{sys.executable}\n" + '''
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["FIXTURE_ROOT"])
calls = root / "go-calls"
attempt = len(calls.read_text().splitlines())
with calls.open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
outcomes = json.loads((root / "outcomes").read_text())
if attempt >= len(outcomes):
    sys.exit("unexpected extra go invocation")
code, message = outcomes[attempt]
print(message, file=sys.stderr if code else sys.stdout)
sys.exit(code)
''')
        self.shell_stub("git", '''
printf '%s\\n' "$*" >> "$FIXTURE_ROOT/git-calls"
test "$1" = -C
test "$2" = "$EXPECTED_DIR"
test "$3" = rev-parse
test "$4" = HEAD:u-root
if [ "${GIT_RC:-0}" -ne 0 ]; then exit "$GIT_RC"; fi
printf '%s\\n' "$EXPECTED_COMMIT"
''')
        self.shell_stub("sleep", 'printf "%s\\n" "$*" >> "$FIXTURE_ROOT/sleeps"\n')
        self.shell_stub("nproc", "printf '2\\n'\n")
        self.shell_stub("timeout", '''
printf '%s\\n' "$*" >> "$FIXTURE_ROOT/timeouts"
test "$1" = 30m
test "$2" = bash
test "$3" = -lc
# Keep the fixture PATH instead of loading the host's login profile.
exec /bin/bash -c "$4"
''')
        self.shell_stub("make", '''
printf '%s\\n' "$*" >> "$FIXTURE_ROOT/make-calls"
test "$1" = -C
test "$2" = "$EXPECTED_DIR"
test "$3" = -j2
test "$4" = arm64
printf '%s\\n' "${BUILD_MESSAGE:-fixture image build}"
exit "${BUILD_RC:-0}"
''')

    def stub(self, name, source):
        target = self.bin / name
        target.write_text(source)
        target.chmod(0o755)

    def shell_stub(self, name, source):
        self.stub(name, "#!/bin/bash\nset -euo pipefail\n" + source)

    def run_setup(self, step_id, outcomes, **env):
        # Execute the actual workflow from gitlink lookup through the one-shot build.
        # Provisioning and unchanged image inspection are outside this focused fixture.
        script = self.steps[step_id]["run"]
        start = script.index("UROOT_COMMIT=")
        if step_id == "install":
            script = script[start:script.index('test -f "${BASE_DIR}/images/', start)]
        else:
            helper_start = script.index("fail_regression()")
            helper_end = script.index("\nunexpected_regression_failure()", helper_start)
            helper = script[helper_start:helper_end]
            body_end = script.index("\nif ! NEXT_VERSION=", start)
            script = helper + "\n" + script[start:body_end]
        script = script.replace("/tmp/submarine-", str(self.root / "submarine-"))
        directory = self.env["BASE_DIR" if step_id == "install" else "NEXT_DIR"]
        commit = "eadd8c6fee2e915e8f331b1c532be4ac98ba2a05" if step_id == "install" else "a" * 40
        for name in ("go-calls", "git-calls", "sleeps", "make-calls", "timeouts", "output"):
            (self.root / name).write_text("")
        (self.root / "outcomes").write_text(json.dumps(outcomes))
        result = subprocess.run(
            ["/bin/bash", "-e", "-u", "-o", "pipefail", "-c", script],
            cwd=self.root,
            env=dict(self.env, EXPECTED_DIR=directory, EXPECTED_COMMIT=commit, **env),
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual([], list(self.tmp.iterdir()), "Setup log should be cleaned up")
        self.assertEqual([f"-C {directory} rev-parse HEAD:u-root"], self.lines("git-calls"))
        for call in self.lines("go-calls"):
            self.assertEqual(["install", f"github.com/u-root/u-root@{commit}"], json.loads(call))
        return result

    def lines(self, name):
        return (self.root / name).read_text().splitlines()

    def run_candidate_source_preflight(self, scenario):
        self.shell_stub("git", r'''
printf '%s\n' "$*" >> "$FIXTURE_ROOT/git-calls"
scenario="${GIT_SCENARIO:-success}"
if [ "$1" = clone ]; then
    target="${!#}"
    mkdir -p "$target/u-root" "$target/kernel"
    exit 0
fi
if [ "$1" = config ] && [ "$2" = --global ]; then
    exit 0
fi
test "$1" = -C
directory="$2"
shift 2
if [ "$directory" = "$NEXT_DIR" ] && [ "$1" = rev-parse ] && [ "$2" = HEAD ]; then
    if [ "$scenario" = parent-mismatch ]; then printf '%040d\n' 9; else printf '%s\n' "$SUBMARINE_NEXT_SOURCE_COMMIT"; fi
elif [ "$directory" = "$NEXT_DIR" ] && [ "$1" = config ] && [ "$2" = -f ]; then
    if [ "$scenario" = bad-upstream ]; then printf '%s\n' 'https://example.invalid/linux.git'; else printf '%s\n' "$SUBMARINE_KERNEL_UPSTREAM"; fi
elif [ "$directory" = "$NEXT_DIR" ] && [ "$1" = config ] && [ "$2" = submodule.kernel.url ]; then
    test "$3" = "$SUBMARINE_KERNEL_MIRROR"
elif [ "$directory" = "$NEXT_DIR" ] && [ "$1" = submodule ] && [ "$2" = update ]; then
    [ "$scenario" != submodule-fetch-fail ]
elif [ "$directory" = "$NEXT_DIR" ] && [ "$1" = rev-parse ] && [ "$2" = HEAD:u-root ]; then
    printf '1111111111111111111111111111111111111111\n'
elif [ "$directory" = "$NEXT_DIR" ] && [ "$1" = rev-parse ] && [ "$2" = HEAD:kernel ]; then
    printf '2222222222222222222222222222222222222222\n'
elif [ "$directory" = "$NEXT_DIR/u-root" ] && [ "$1" = rev-parse ] && [ "$2" = HEAD ]; then
    if [ "$scenario" = submodule-mismatch ]; then printf '%040d\n' 8; else printf '1111111111111111111111111111111111111111\n'; fi
elif [ "$directory" = "$NEXT_DIR/kernel" ] && [ "$1" = rev-parse ] && [ "$2" = HEAD ]; then
    printf '2222222222222222222222222222222222222222\n'
else
    exit 91
fi
''')
        full_script = self.steps["test6"]["run"]
        helper_start = full_script.index("fail_regression()")
        helper_end = full_script.index("\nunexpected_regression_failure()", helper_start)
        source_start = full_script.index('rm -rf "${NEXT_DIR}"')
        source_end = full_script.index("UROOT_COMMIT=", source_start)
        script = full_script[helper_start:helper_end] + "\n" + full_script[source_start:source_end]
        for name in ("git-calls", "output"):
            (self.root / name).write_text("")
        result = subprocess.run(
            ["/bin/bash", "-e", "-u", "-o", "pipefail", "-c", script],
            cwd=self.root,
            env=dict(self.env, GIT_SCENARIO=scenario),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result, self.lines("output"), self.lines("git-calls")

    def test_success_does_not_retry_or_sleep(self):
        for step in ("install", "test6"):
            with self.subTest(step=step):
                result = self.run_setup(step, [(0, "u-root installed")])
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("u-root installed", result.stdout)
                self.assertEqual(1, len(self.lines("go-calls")))
                self.assertEqual([], self.lines("sleeps"))
                self.assertEqual(1, len(self.lines("make-calls")))

    def test_gateway_failure_recovers_with_bounded_backoff(self):
        for step in ("install", "test6"):
            for status in (502, 503, 504):
                for failures in (1, 2):
                    with self.subTest(step=step, status=status, failures=failures):
                        message = DOWNLOAD_ERROR.replace("502", str(status))
                        result = self.run_setup(step, [(1, message)] * failures + [(0, "ready")])
                        self.assertEqual(0, result.returncode, result.stderr)
                        self.assertEqual(failures, result.stderr.count(message))
                        self.assertEqual(failures + 1, len(self.lines("go-calls")))
                        self.assertEqual(["5", "10"][:failures], self.lines("sleeps"))
                        self.assertEqual(1, len(self.lines("make-calls")))

    def test_exhaustion_preserves_final_exit_code_and_blocks_build(self):
        for step in ("install", "test6"):
            with self.subTest(step=step):
                result = self.run_setup(step, [(1, DOWNLOAD_ERROR), (2, DOWNLOAD_ERROR), (37, DOWNLOAD_ERROR)])
                self.assertEqual(37 if step == "install" else 1, result.returncode, result.stderr)
                self.assertEqual(3, result.stderr.count(DOWNLOAD_ERROR))
                self.assertEqual(3, len(self.lines("go-calls")))
                self.assertEqual(["5", "10"], self.lines("sleeps"))
                self.assertEqual([], self.lines("timeouts"))
                self.assertEqual([], self.lines("make-calls"))
                if step == "install":
                    self.assertEqual([], self.lines("output"))
                else:
                    self.assertIn("decision=next_install_failed", self.lines("output"))
                    self.assertIn("status=failed", self.lines("output"))

    def test_non_gateway_errors_fail_immediately_with_original_exit_code(self):
        errors = (
            "# github.com/u-root/u-root\nundefined: missingSymbol",
            "verifying module: checksum mismatch\nSECURITY ERROR",
            DOWNLOAD_ERROR.replace("502 Proxy Error", "404 Not Found"),
            DOWNLOAD_ERROR.replace("502 Proxy Error", "403 Forbidden"),
            'go: invalid version: unknown revision deadbeef',
            'templates.go:502: undefined: ProxyError',
        )
        for step in ("install", "test6"):
            for message in errors:
                with self.subTest(step=step, message=message):
                    result = self.run_setup(step, [(23, message)])
                    self.assertEqual(23 if step == "install" else 1, result.returncode, result.stderr)
                    self.assertIn(message, result.stderr)
                    self.assertEqual(1, len(self.lines("go-calls")))
                    self.assertEqual([], self.lines("sleeps"))
                    self.assertEqual([], self.lines("make-calls"))

    def test_old_gateway_log_cannot_retry_a_subsequent_compiler_failure(self):
        for step in ("install", "test6"):
            with self.subTest(step=step):
                result = self.run_setup(step, [(1, DOWNLOAD_ERROR), (19, "undefined: missingSymbol")])
                self.assertEqual(19 if step == "install" else 1, result.returncode, result.stderr)
                self.assertEqual(2, len(self.lines("go-calls")))
                self.assertEqual(["5"], self.lines("sleeps"))
                self.assertEqual([], self.lines("make-calls"))

    def test_gitlink_lookup_failure_is_not_retried_or_ignored(self):
        for step in ("install", "test6"):
            with self.subTest(step=step):
                result = self.run_setup(step, [], GIT_RC="41")
                self.assertEqual(41, result.returncode, result.stderr)
                self.assertEqual([], self.lines("go-calls"))
                self.assertEqual([], self.lines("sleeps"))
                self.assertEqual([], self.lines("make-calls"))

    def test_image_build_failure_is_not_retried_even_for_a_network_error(self):
        for step in ("install", "test6"):
            for setup in ([(0, "ready")], [(1, DOWNLOAD_ERROR), (0, "ready")]):
                with self.subTest(step=step, setup=setup):
                    result = self.run_setup(step, setup, BUILD_RC="29", BUILD_MESSAGE=DOWNLOAD_ERROR)
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertIn(DOWNLOAD_ERROR, result.stdout)
                    self.assertEqual(len(setup), len(self.lines("go-calls")))
                    self.assertEqual(["5"] if len(setup) == 2 else [], self.lines("sleeps"))
                    self.assertEqual(1, len(self.lines("make-calls")))
                    self.assertEqual(1, len(self.lines("timeouts")))
                    if step == "test6":
                        self.assertIn("status=failed", self.lines("output"))
                        self.assertIn("decision=next_install_failed", self.lines("output"))

    def test_pins_source_and_test_scope_are_preserved(self):
        self.assertEqual("0.4.0", self.job["env"]["SUBMARINE_VERSION"])
        self.assertEqual(
            "8e53f27f9f4b41ba4ea960ad7b8d3781eae6cb8d",
            self.job["env"]["SUBMARINE_SOURCE_COMMIT"],
        )
        self.assertEqual("0.5.1", self.job["env"]["SUBMARINE_NEXT_VERSION"])
        self.assertEqual(
            "a2e60395030115263af276eabd6f8da0a21a84a9",
            self.job["env"]["SUBMARINE_NEXT_SOURCE_COMMIT"],
        )
        self.assertEqual("https://github.com/FyraLabs/submarine.git", self.job["env"]["SUBMARINE_REPO"])
        self.assertEqual(
            "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git",
            self.job["env"]["SUBMARINE_KERNEL_UPSTREAM"],
        )
        self.assertEqual(
            "https://github.com/gregkh/linux.git",
            self.job["env"]["SUBMARINE_KERNEL_MIRROR"],
        )
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual(
            "registry.fedoraproject.org/fedora-minimal@sha256:"
            "c8f378f1927145aa7cf5c4c5044ba13fbfc0725aa61b626eb05caa73eea9b86a",
            self.job["container"]["image"],
        )
        for step, version, directory in (("install", "SUBMARINE_VERSION", "BASE_DIR"), ("test6", "LATEST", "NEXT_DIR")):
            script = self.steps[step]["run"]
            self.assertIn(
                f'git clone --depth 1 --branch "v${{{version}}}" '
                f'"${{SUBMARINE_REPO}}" "${{{directory}}}"',
                script,
            )
            self.assertNotIn("--recurse-submodules", script)
            source_commit = (
                "SUBMARINE_SOURCE_COMMIT" if step == "install" else "SUBMARINE_NEXT_SOURCE_COMMIT"
            )
            self.assertIn(source_commit, script)
            self.assertIn(
                f'git -C "${{{directory}}}" config -f .gitmodules '
                "--get submodule.kernel.url",
                script,
            )
            self.assertIn(
                f'git -C "${{{directory}}}" config submodule.kernel.url '
                '"${SUBMARINE_KERNEL_MIRROR}"',
                script,
            )
            self.assertIn(
                f'git -C "${{{directory}}}" submodule update --init --depth 1 '
                "--jobs 2 u-root kernel",
                script,
            )
            self.assertIn(
                f'EXPECTED_SUBMODULE_COMMIT=$(git -C "${{{directory}}}" '
                'rev-parse "HEAD:${SUBMODULE}")',
                script,
            )
            self.assertIn(
                f'ACTUAL_SUBMODULE_COMMIT=$(git -C "${{{directory}}}/${{SUBMODULE}}" '
                "rev-parse HEAD)",
                script,
            )
            if step == "install":
                self.assertIn(
                    'test "${ACTUAL_SUBMODULE_COMMIT}" = "${EXPECTED_SUBMODULE_COMMIT}"',
                    script,
                )
            else:
                self.assertIn(
                    '[ "${ACTUAL_SUBMODULE_COMMIT}" != "${EXPECTED_SUBMODULE_COMMIT}" ]',
                    script,
                )
            self.assertEqual(1, script.count("go install "))
            self.assertEqual(1, script.count("timeout 30m bash -lc"))
        for number in range(1, 6):
            self.assertNotRegex(self.steps[f"test{number}"]["run"], r"(?i)retry|ATTEMPT|sleep ")
        self.assertNotRegex(WORKFLOW.read_text(), r"GOPROXY|GOSUMDB|GONOSUMDB|insecure")

    def test_regression_failures_emit_policy_approved_outputs(self):
        script = self.steps["test6"]["run"]
        for decision in (
            "next_download_failed",
            "next_source_preflight_failed",
            "next_install_failed",
            "next_artifact_validation_failed",
        ):
            self.assertIn(f'"{decision}"', script)
        self.assertIn("fail_regression()", script)
        self.assertIn("trap unexpected_regression_failure ERR", script)
        self.assertIn('echo "status=failed"', script)
        self.assertIn('echo "duration=$((end_time - START_TIME))"', script)

    def test_candidate_source_preflight_executes_mirror_and_gitlink_guards(self):
        result, output, calls = self.run_candidate_source_preflight("success")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], output)
        self.assertTrue(any("submodule update --init --depth 1 --jobs 2 u-root kernel" in call for call in calls))

        for scenario, decision in (
            ("parent-mismatch", "next_source_preflight_failed"),
            ("bad-upstream", "next_source_preflight_failed"),
            ("submodule-fetch-fail", "next_download_failed"),
            ("submodule-mismatch", "next_source_preflight_failed"),
        ):
            with self.subTest(scenario=scenario):
                result, output, calls = self.run_candidate_source_preflight(scenario)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertIn(f"decision={decision}", output)
                self.assertIn("status=failed", output)
                if scenario in {"parent-mismatch", "bad-upstream"}:
                    self.assertFalse(any("submodule update" in call for call in calls))

    def test_summary_counts_skipped_regression_separately(self):
        script = self.steps["summary"]["run"]
        self.assertIn("SKIPPED=0", script)
        self.assertIn("skipped) SKIPPED=$((SKIPPED + 1))", script)
        self.assertIn('echo "skipped=${SKIPPED}"', script)
        self.assertNotIn(
            'if [ "${{ steps.test6.outputs.status || \'failed\' }}" = "passed" ]',
            script,
        )
    def test_candidate_failure_cannot_leave_the_summary_green(self):
        for candidate in ("passed", "failed", "", "skipped"):
            with self.subTest(candidate=candidate):
                def expression(match):
                    number, field = match.group(1), match.group(2)
                    if field == "duration":
                        return "1"
                    return (candidate or "failed") if number == "6" else "passed"
                script = re.sub(
                    r"\$\{\{ steps\.test([1-6])\.outputs\.(status|duration) \|\| .*? \}\}",
                    expression, self.steps["summary"]["run"],
                )
                self.assertNotIn("${{", script)
                output = Path(self.env["GITHUB_OUTPUT"])
                output.write_text("")
                result = subprocess.run(
                    ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
                    cwd=self.root, env=self.env, capture_output=True, text=True, timeout=10,
                )
                values = dict(line.split("=", 1) for line in output.read_text().splitlines())
                non_failing = candidate in {"passed", "skipped"}
                self.assertEqual(0 if non_failing else 1, result.returncode, result.stderr)
                self.assertEqual("6" if candidate == "passed" else "5", values["passed"])
                self.assertEqual("0" if non_failing else "1", values["failed"])
                self.assertEqual("1" if candidate == "skipped" else "0", values["skipped"])
                self.assertEqual("0", values["core_failed"])
                self.assertEqual("success" if non_failing else "failure", values["overall_status"])
                self.assertEqual("passing" if non_failing else "failing", values["badge_status"])

    def test_shell_steps_parse(self):
        for step in self.job["steps"]:
            if "run" in step:
                script = re.sub(r"\$\{\{.*?\}\}", "fixture", step["run"])
                result = subprocess.run(["/bin/bash", "-n"], input=script, capture_output=True, text=True)
                self.assertEqual(0, result.returncode, step["name"] + result.stderr)


if __name__ == "__main__":
    unittest.main()
