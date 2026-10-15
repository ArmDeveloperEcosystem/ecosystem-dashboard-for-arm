"""Exercise bounded clone recovery in the actual BoringSSL install script."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-boringssl.yml"


class BoringSSLWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="boringssl-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-boringssl"]
        self.script = next(step["run"] for step in job["steps"] if step.get("id") == "install")
        self.env = dict(os.environ, **job["env"], PATH=str(self.bin),
                        GITHUB_WORKSPACE=str(self.root), GITHUB_OUTPUT=str(self.root / "output"),
                        TMPDIR=str(self.root), CALLS=str(self.root / "calls"),
                        CLONE_ATTEMPTS=str(self.root / "attempts"), REAL_RM=shutil.which("rm"),
                        CLONE_FAILURES="0", CLONE_FAILURE_KIND="503", TIMEOUT_RC="124",
                        CMAKE_RC="0", NINJA_RC="0", MISSING_BINARY="0")
        self.env.pop("BASH_ENV", None)

        # Only these real filesystem utilities are exposed; host Go and timeout are never used.
        for command in ("mkdir", "find", "head", "cp"):
            (self.bin / command).symlink_to(shutil.which(command))
        self.stub("go", "exit 0")
        self.stub("rm", r'''
exec "$REAL_RM" "$@"
''')
        self.stub("sleep", "exit 0")
        self.stub("timeout", r'''
test "$1" = --kill-after=10s
test "$2" = 180s
shift 2
if "$@"; then
  exit 0
else
  status=$?
fi
if [ "$CLONE_FAILURE_KIND" = timeout ]; then
  echo "fixture: clone timed out ($TIMEOUT_RC)" >&2
  exit "$TIMEOUT_RC"
fi
exit "$status"
''')
        self.stub("git", r'''
read -r attempt < "$CLONE_ATTEMPTS"
attempt=$((attempt + 1))
printf '%s\n' "$attempt" > "$CLONE_ATTEMPTS"
if [ -e boringssl ] || [ -L boringssl ]; then
  echo "fixture: clone destination was not cleaned" >&2
  exit 97
fi
mkdir boringssl
if [ "$attempt" -le "$CLONE_FAILURES" ]; then
  printf 'partial clone %s\n' "$attempt" > boringssl/partial
  if [ "$CLONE_FAILURE_KIND" = 503 ]; then
    echo 'fatal: unable to access upstream: The requested URL returned error: 503' >&2
  fi
  exit 128
fi
printf 'fixture source\n' > boringssl/source
''')
        self.stub("cmake", r'''
test "$PWD" = "$GITHUB_WORKSPACE/boringssl/build"
test -f ../source
exit "$CMAKE_RC"
''')
        self.stub("ninja", r'''
test "$PWD" = "$GITHUB_WORKSPACE/boringssl/build"
if [ "$NINJA_RC" -ne 0 ]; then exit "$NINJA_RC"; fi
mkdir -p tool
if [ "$MISSING_BINARY" = 1 ]; then
  mkdir tool/bssl
else
  printf 'fixture bssl\n' > tool/bssl
fi
''')

    def stub(self, name, body):
        path = self.bin / name
        log = (f"printf '%s' {shlex.quote(name)} >> \"$CALLS\"\n"
               "printf ' %q' \"$@\" >> \"$CALLS\"\n"
               "printf '\\n' >> \"$CALLS\"\n")
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + log + body + "\n")
        path.chmod(0o755)

    def run_install(self, **environment):
        Path(self.env["GITHUB_OUTPUT"]).write_text("")
        Path(self.env["CALLS"]).write_text("")
        Path(self.env["CLONE_ATTEMPTS"]).write_text("0\n")
        (self.root / "bssl").unlink(missing_ok=True)
        source = self.root / "boringssl"
        source.mkdir(exist_ok=True)
        (source / "partial").write_text("stale checkout\n")
        result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", self.script],
                                cwd=self.root, env={**self.env, **environment},
                                capture_output=True, text=True, timeout=15)
        outputs = dict(line.split("=", 1) for line in
                       Path(self.env["GITHUB_OUTPUT"]).read_text().splitlines())
        calls = [shlex.split(line) for line in Path(self.env["CALLS"]).read_text().splitlines()]
        self.assertNotIn("fixture: clone destination was not cleaned", result.stderr)
        return result, outputs, calls

    def clone_calls(self, attempts):
        clone = ["git", "clone", "--depth", "1", "--branch", "fips-20220613",
                 "https://boringssl.googlesource.com/boringssl", "boringssl"]
        calls = []
        for attempt in range(1, attempts + 1):
            calls.extend([["rm", "-rf", "boringssl"],
                          ["timeout", "--kill-after=10s", "180s", *clone], clone])
            if attempt < attempts:
                calls.append(["sleep", str(attempt * 5)])
        return calls

    def build_calls(self):
        return [["cmake", "-GNinja", f"-DGO_EXECUTABLE={self.bin / 'go'}",
                 "-DBUILD_SHARED_LIBS=0", "-DRUN_TESTS=0", "-DCMAKE_C_COMPILER=clang",
                 "-DCMAKE_CXX_COMPILER=clang++", "-DCMAKE_BUILD_TYPE=Release",
                 "-DCMAKE_VERBOSE_MAKEFILE=ON", ".."],
                ["ninja", "-j", "2", "-v", "bssl"]]

    def assert_clone_success(self, failures):
        result, output, calls = self.run_install(CLONE_FAILURES=str(failures))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual({"install_status": "success"}, output)
        self.assertEqual(self.clone_calls(failures + 1) + self.build_calls(), calls)
        self.assertFalse((self.root / "boringssl/partial").exists())
        self.assertEqual("fixture bssl\n", (self.root / "bssl").read_text())

    def test_first_clone_succeeds_without_retry(self):
        self.assert_clone_success(0)

    def test_second_clone_succeeds_after_partial_clone_cleanup(self):
        self.assert_clone_success(1)

    def test_third_clone_succeeds_after_partial_clone_cleanup(self):
        self.assert_clone_success(2)

    def test_persistent_503_stops_after_three_clones_without_building(self):
        result, output, calls = self.run_install(CLONE_FAILURES="99")
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual({"install_status": "failed"}, output)
        self.assertEqual(self.clone_calls(3), calls)
        self.assertEqual(3, result.stderr.count("The requested URL returned error: 503"))
        self.assertFalse((self.root / "boringssl/build").exists())
        self.assertFalse((self.root / "bssl").exists())

    def test_persistent_timeouts_stop_after_three_attempts_without_building(self):
        for status in ("124", "137"):
            with self.subTest(timeout_status=status):
                result, output, calls = self.run_install(
                    CLONE_FAILURES="99", CLONE_FAILURE_KIND="timeout", TIMEOUT_RC=status)
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertEqual({"install_status": "failed"}, output)
                self.assertEqual(self.clone_calls(3), calls)
                self.assertEqual(3, result.stderr.count(f"fixture: clone timed out ({status})"))
                self.assertFalse((self.root / "boringssl/build").exists())
                self.assertFalse((self.root / "bssl").exists())

    def test_missing_go_fails_before_cloning(self):
        (self.bin / "go").unlink()
        result, output, calls = self.run_install()
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual({"install_status": "failed"}, output)
        self.assertIn("Go toolchain not found in PATH", result.stderr)
        self.assertEqual([], calls)
        self.assertFalse((self.root / "bssl").exists())

    def test_cmake_and_ninja_failures_are_not_retried_or_hidden(self):
        for failures in ("0", "2"):
            for command, status, build_count in (("CMAKE_RC", "23", 1), ("NINJA_RC", "42", 2)):
                with self.subTest(command=command, clone_failures=failures):
                    result, output, calls = self.run_install(
                        CLONE_FAILURES=failures, **{command: status})
                    self.assertEqual(int(status), result.returncode, result.stdout + result.stderr)
                    self.assertNotEqual("success", output.get("install_status"))
                    self.assertEqual(self.clone_calls(int(failures) + 1) +
                                     self.build_calls()[:build_count], calls)
                    self.assertFalse((self.root / "bssl").exists())

    def test_missing_built_binary_fails_without_retry(self):
        result, output, calls = self.run_install(MISSING_BINARY="1")
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual({"install_status": "failed"}, output)
        self.assertIn("BoringSSL build failed - binary not found", result.stdout)
        self.assertEqual(self.clone_calls(1) + self.build_calls(), calls)
        self.assertFalse((self.root / "bssl").exists())


if __name__ == "__main__":
    unittest.main()
