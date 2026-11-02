"""Exercise EMQTT Git transport and failure reporting in the actual workflow scripts."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-emqtt.yml"
SOURCE = "https://boringssl.googlesource.com/boringssl"
MIRROR = "https://github.com/google/boringssl"
BORINGSSL_COMMIT = "2070f8ad9151dc8f3a73bffaa146b5e6937a583f"
GIT_ENV = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{MIRROR}.insteadOf",
           "GIT_CONFIG_VALUE_0": SOURCE}
OPENSSL_PATH = "_build/default/lib/quicer/c_src/msquic/submodules/openssl"


class EmqttWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="emqtt-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.job = self.workflow["jobs"]["test-emqtt"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.git = os.environ.get("EMQTT_TEST_GIT") or shutil.which("git")
        self.assertIsNotNone(self.git, "Git is required for URL resolution tests")
        self.global_config = self.root / "gitconfig"
        self.global_config.write_text("[user]\n\tname = fixture\n")
        self.template = self.root / "empty-template"
        self.template.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("GIT_") and key != "BASH_ENV"}
        self.env.update(self.job["env"], PATH=str(self.bin), HOME=str(self.root),
                        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(self.global_config),
                        XDG_CONFIG_HOME=str(self.root / "config"),
                        GIT_TEMPLATE_DIR=str(self.template), REAL_GIT=self.git,
                        GITHUB_OUTPUT=str(self.root / "output"), GITHUB_WORKSPACE=str(self.root),
                        RUNNER_TEMP=str(self.root), TMPDIR=str(self.root),
                        CALLS=str(self.root / "calls"), FIXTURE_BIN=str(self.bin),
                        FIXTURE_OPENSSL_PATH=OPENSSL_PATH, FIXTURE_BORINGSSL_COMMIT=BORINGSSL_COMMIT,
                        FIXTURE_SOURCE=SOURCE, CLONE_RC="0", NESTED_GIT_RC="0", MAKE_RC="0")
        for command in ("bash", "rm", "mkdir", "cp", "chmod", "find", "head", "date",
                        "mktemp", "grep", "tail", "cut", "cat"):
            executable = "/bin/bash" if command == "bash" else shutil.which(command)
            (self.bin / command).symlink_to(executable)
        (self.bin / "python3").symlink_to(sys.executable)

        self.stub(".github/actions/apt-bootstrap/bootstrap.sh", "exit 0", directory=self.root)
        self.stub("git", r'''
case "$1" in
  ls-remote)
    test "$*" = 'ls-remote --tags https://github.com/emqx/emqtt.git'
    printf '%s\trefs/tags/%s\n' "$FIXTURE_BORINGSSL_COMMIT" 2.0.0 \
      "$FIXTURE_BORINGSSL_COMMIT" 1.4.4 "$FIXTURE_BORINGSSL_COMMIT" 1.5.0
    ;;
  clone)
    test "$#" = 7
    if [ "$CLONE_RC" -ne 0 ]; then echo 'source clone failed' >&2; exit "$CLONE_RC"; fi
    mkdir -p "$7/$FIXTURE_OPENSSL_PATH"
    cd "$7/$FIXTURE_OPENSSL_PATH"
    "$REAL_GIT" init --quiet
    "$REAL_GIT" config --file .gitmodules submodule.boringssl.path boringssl
    "$REAL_GIT" config --file .gitmodules submodule.boringssl.url "$FIXTURE_SOURCE"
    "$REAL_GIT" update-index --add --cacheinfo "160000,$FIXTURE_BORINGSSL_COMMIT,boringssl"
    ;;
  *) echo "Unexpected Git command: $*" >&2; exit 98 ;;
esac
''')
        self.stub("rebar3", r'''
case "$1" in
  version) echo 'rebar 3.20 fixture' ;;
  compile) quictls-build ;;
  *) exit 98 ;;
esac
''')
        # Model make -> rebar3 -> nested build -> real Git, without downloading or compiling.
        self.stub("quictls-build", r'''
cd "$FIXTURE_OPENSSL_PATH"
source_url=$("$REAL_GIT" config --file .gitmodules --get submodule.boringssl.url)
resolved=$("$REAL_GIT" ls-remote --get-url "$source_url")
printf 'transport %q %q %q %q\n' "${GIT_CONFIG_COUNT:-}" "${GIT_CONFIG_KEY_0:-}" \
  "${GIT_CONFIG_VALUE_0:-}" "$resolved" >> "$CALLS"
printf 'gitlink %s\n' "$("$REAL_GIT" ls-files --stage -- boringssl)" >> "$CALLS"
if [ "$NESTED_GIT_RC" -ne 0 ]; then echo 'nested clone failed' >&2; fi
exit "$NESTED_GIT_RC"
''')
        self.stub("make", r'''
test "$*" = escript
test "$CFLAGS" = ' -Wno-error=dangling-pointer -Wno-dangling-pointer'
test "$CMAKE_C_FLAGS" = ' -Wno-error=dangling-pointer -Wno-dangling-pointer'
./rebar3 compile
if [ "$MAKE_RC" -ne 0 ]; then echo 'make escript failed' >&2; exit "$MAKE_RC"; fi
mkdir -p _build/escript/bin
cp "$FIXTURE_BIN/fixture-emqtt-cli" _build/escript/bin/emqtt_cli
''')
        self.stub("fixture-emqtt-cli", "echo 'Usage: emqtt pub --payload --topic'")
        self.stub("sudo", r'''
test "$#" = 3
test "$3" = /usr/local/bin/emqtt_cli
case "$1" in
  cp) cp "$2" "$FIXTURE_BIN/emqtt_cli" ;;
  chmod) chmod "$2" "$FIXTURE_BIN/emqtt_cli" ;;
  *) exit 98 ;;
esac
''')
        self.env.update(CFLAGS="", CMAKE_C_FLAGS="")

    def stub(self, name, body, directory=None):
        path = (directory or self.bin) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        log = (f"printf '%s' {shlex.quote(name)} >> \"$CALLS\"\n"
               "printf ' %q' \"$@\" >> \"$CALLS\"\n"
               "printf '\\n' >> \"$CALLS\"\n")
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + log + body + "\n")
        path.chmod(0o755)

    def real_git(self, *args, environment=None, cwd=None):
        return subprocess.check_output([self.git, *args], cwd=cwd or self.root,
                                       env={**self.env, **(environment or {})},
                                       text=True, stderr=subprocess.PIPE, timeout=10).strip()

    def run_step(self, step_id, *, step_outputs=None, **environment):
        step = self.steps[step_id]
        values = {"steps.version.outputs.version": "1.4.4"}
        for source_step, outputs in (step_outputs or {}).items():
            values.update({f"steps.{source_step}.outputs.{key}": value
                           for key, value in outputs.items()})

        def expression(match):
            for term in match[1].split("||"):
                key = term.strip()
                value = (key[1:-1] if key.startswith("'") else
                         key if key.isdigit() else
                         self.env.get(key[4:]) if key.startswith("env.") else values.get(key))
                if value:
                    return str(value)
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, step["run"])
        # Isolate the existing candidate's absolute diagnostic path from other test processes.
        script = script.replace("/tmp/emqtt-next-pub-help.log", str(self.root / "pub-help.log"))
        for name in ("GITHUB_OUTPUT", "CALLS"):
            Path(self.env[name]).write_text("")
        (self.bin / "emqtt_cli").unlink(missing_ok=True)
        result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env={**self.env, **step.get("env", {}), **environment},
                                capture_output=True, text=True, timeout=20)
        output = dict(line.split("=", 1) for line in
                      Path(self.env["GITHUB_OUTPUT"]).read_text().splitlines())
        calls = [shlex.split(line) for line in Path(self.env["CALLS"]).read_text().splitlines()]
        return result, output, calls

    def assert_summary_with_passing_baseline(self, candidate_output, *, passed, failed, skipped):
        step_outputs = {f"test{i}": {"status": "passed", "duration": str(i)}
                        for i in range(1, 6)}
        step_outputs["test6"] = candidate_output
        result, output, _ = self.run_step("summary", step_outputs=step_outputs)
        self.assertEqual({"passed": str(passed), "failed": str(failed), "skipped": str(skipped),
                          "duration": str(15 + int(candidate_output.get("duration", "0"))),
                          "core_failed": "0", "overall_status": "failure" if failed else "success",
                          "badge_status": "failing" if failed else "passing"}, output)
        self.assertEqual(1 if failed else 0, result.returncode, result.stdout + result.stderr)

    def assert_transport_and_pins(self, step_id, calls):
        self.assertEqual([["transport", "1", GIT_ENV["GIT_CONFIG_KEY_0"], SOURCE, MIRROR]],
                         [call for call in calls if call[0] == "transport"])
        expected_pin = ["160000", BORINGSSL_COMMIT, "0", "boringssl"]
        self.assertEqual([["gitlink", *expected_pin]],
                         [call for call in calls if call[0] == "gitlink"])
        clones = [call for call in calls if call[:2] == ["git", "clone"]]
        self.assertEqual(1, len(clones))
        version = "1.4.4" if step_id == "install" else "1.5.0"
        self.assertEqual(["git", "clone", "--depth", "1", "--branch", version,
                          "https://github.com/emqx/emqtt.git"], clones[0][:-1])
        openssl = Path(clones[0][-1]) / OPENSSL_PATH
        self.assertEqual(expected_pin, self.real_git("ls-files", "--stage", "--", "boringssl",
                                                    cwd=openssl).split())
        self.assertEqual(SOURCE, self.real_git("config", "--file", ".gitmodules", "--get",
                                              "submodule.boringssl.url", cwd=openssl))
        self.assertEqual(SOURCE, self.real_git("ls-remote", "--get-url", SOURCE, cwd=openssl))
        self.assertEqual("[user]\n\tname = fixture\n", self.global_config.read_text())
        self.assertEqual([["make", "escript"]], [call for call in calls if call[0] == "make"])
        self.assertEqual([["rebar3", "version"], ["rebar3", "compile"]],
                         [call for call in calls if call[0] == "rebar3"])

    def test_transport_configuration_is_scoped_to_both_compile_steps(self):
        self.assertEqual("1.4.4", self.job["env"]["EMQTT_VERSION"])
        self.assertEqual("https://github.com/emqx/emqtt", self.job["env"]["EMQTT_REPO"])
        for owner in (self.workflow, self.job, *self.job["steps"]):
            with self.subTest(owner=owner.get("id", owner.get("name", "job"))):
                settings = {key: value for key, value in owner.get("env", {}).items()
                            if key.startswith("GIT_CONFIG_")}
                self.assertEqual(GIT_ENV if owner.get("id") in ("install", "test6") else {}, settings)

    def test_real_git_maps_boringssl_but_not_unrelated_remotes(self):
        urls = {SOURCE: MIRROR, SOURCE + ".git": MIRROR + ".git",
                "https://boringssl.googlesource.com/other": "https://boringssl.googlesource.com/other",
                "https://github.com/emqx/emqtt.git": "https://github.com/emqx/emqtt.git",
                "https://github.com/quictls/openssl.git": "https://github.com/quictls/openssl.git"}
        for step_id in ("install", "test6"):
            for source, expected in urls.items():
                with self.subTest(step=step_id, source=source):
                    self.assertEqual(expected, self.real_git("ls-remote", "--get-url", source,
                                                            environment=self.steps[step_id]["env"]))
        self.assertEqual(SOURCE, self.real_git("ls-remote", "--get-url", SOURCE))

    def test_baseline_build_inherits_transport_and_keeps_pins_and_outputs(self):
        result, output, calls = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_transport_and_pins("install", calls)
        self.assertEqual({"source_dir": str(self.root / "emqtt-1.4.4"),
                          "binary_path": "/usr/local/bin/emqtt_cli", "install_status": "success"}, output)
        self.assertTrue((self.bin / "emqtt_cli").is_file())

    def test_candidate_build_inherits_transport_and_keeps_pins_and_validation(self):
        result, output, calls = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assert_transport_and_pins("test6", calls)
        self.assertEqual("passed", output["status"])
        self.assertEqual("next_install_validated", output["decision"])
        self.assertEqual("1.4.4", output["current_version"])
        self.assertEqual("1.5.0", output["latest_version"])
        self.assertEqual("1.5.0", output["next_installed_version"])
        self.assertEqual([["fixture-emqtt-cli", "pub", "--help"]],
                         [call for call in calls if call[0] == "fixture-emqtt-cli"])

    def test_nested_clone_and_compile_failures_are_not_hidden(self):
        for step_id in ("install", "test6"):
            for failure, status, diagnostic in (("NESTED_GIT_RC", "128", "nested clone failed"),
                                                ("MAKE_RC", "2", "make escript failed")):
                with self.subTest(step=step_id, failure=failure):
                    result, output, calls = self.run_step(step_id, **{failure: status})
                    self.assertEqual(int(status), result.returncode, result.stdout + result.stderr)
                    self.assertIn(diagnostic, result.stderr)
                    self.assert_transport_and_pins(step_id, calls)
                    self.assertNotEqual("success", output.get("install_status"))
                    self.assertNotEqual("passed", output.get("status"))
                    if step_id == "test6":
                        self.assertEqual("failed", output.get("status"))
                    self.assertNotIn("next_installed_version", output)
                    self.assertFalse(any(call[0] in ("sudo", "fixture-emqtt-cli") for call in calls))

    def test_summary_fails_when_candidate_build_aborts_after_five_baseline_passes(self):
        for failure, status in (("CLONE_RC", "128"), ("NESTED_GIT_RC", "128"), ("MAKE_RC", "2")):
            with self.subTest(failure=failure):
                result, output, calls = self.run_step("test6", **{failure: status})
                self.assertEqual(int(status), result.returncode, result.stdout + result.stderr)
                self.assertNotIn("next_installed_version", output)
                self.assertFalse(any(call[0] == "fixture-emqtt-cli" for call in calls))
                self.assert_summary_with_passing_baseline(output, passed=5, failed=1, skipped=0)
                self.assertEqual("failed", output.get("status"))

    def test_summary_passes_for_six_passing_tests(self):
        result, output, _ = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output.get("status"))
        self.assertEqual("next_install_validated", output.get("decision"))
        self.assert_summary_with_passing_baseline(output, passed=6, failed=0, skipped=0)

    def test_summary_allows_no_newer_stable_skip_after_five_baseline_passes(self):
        self.stub("git", r'''
test "$*" = 'ls-remote --tags https://github.com/emqx/emqtt.git'
printf '%s\trefs/tags/1.4.4\n' "$FIXTURE_BORINGSSL_COMMIT"
''')
        result, output, calls = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("skipped", output.get("status"))
        self.assertEqual("no_newer_stable_available", output.get("decision"))
        self.assertEqual("1.4.4", output.get("current_version"))
        self.assertEqual("1.4.4", output.get("latest_version"))
        self.assertEqual([["git", "ls-remote", "--tags", "https://github.com/emqx/emqtt.git"]], calls)
        self.assert_summary_with_passing_baseline(output, passed=5, failed=0, skipped=1)


if __name__ == "__main__":
    unittest.main()
