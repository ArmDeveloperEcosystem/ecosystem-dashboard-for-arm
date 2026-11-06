"""Exercise the removed baseline AppImage's exact-source fallback."""

import unittest

import test_librecad_workflow as workflow_tests


class LibrecadSourceFallbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow_tests.LibrecadWorkflowTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.runtime_fixture()
        self.root = self.fixture.root
        self.fixture.env.update(
            FIXTURE_SOURCE_DIR=str(self.root / "baseline-src"),
            FIXTURE_BUILD_MARKER=str(self.root / "build-started"),
            FIXTURE_RUNTIME_TIMEOUT=str(self.fixture.bin / "runtime-timeout"),
        )
        (self.fixture.bin / "timeout").rename(self.fixture.bin / "runtime-timeout")
        self.fixture.stub("timeout", r'''
if [ "$1" != --kill-after=60s ]; then exec "$FIXTURE_RUNTIME_TIMEOUT" "$@"; fi
case "$2" in
  5m) rc="${FIXTURE_QMAKE_TIMEOUT_RC:-0}" ;;
  30m) rc="${FIXTURE_BUILD_TIMEOUT_RC:-0}" ;;
  *) exit 99 ;;
esac
if [ "$rc" != 0 ]; then exit "$rc"; fi
shift 2
exec "$@"
''')
        self.fixture.stub("curl", r'''
test "$1" = -fsSL
test "$2" = -w
test "$3" = '%{http_code}'
test "$4" = "https://github.com/LibreCAD/LibreCAD/releases/download/v2.2.1.1/LibreCAD-v2.2.1.1-aarch64.AppImage"
test "$5" = -o
printf '%s' "${FIXTURE_HTTP_STATUS:-404}"
if [ "${FIXTURE_DOWNLOAD_RC:-22}" != 0 ]; then exit "${FIXTURE_DOWNLOAD_RC:-22}"; fi
if [ "${FIXTURE_CORRUPT_DOWNLOAD:-0}" = 1 ]; then
  printf '<html>Not an AppImage</html>\n' > "$6"
  exit 0
fi
cp "$FIXTURE_EXTRACTOR" "$6"
''')
        self.fixture.stub("git", r'''
test "$PWD" = "$FIXTURE_SOURCE_DIR"
case "$*" in
  'remote get-url origin') echo "${FIXTURE_ORIGIN:-https://github.com/LibreCAD/LibreCAD.git}" ;;
  'describe --tags --exact-match HEAD') echo "${FIXTURE_TAG:-v2.2.1.1}" ;;
  'rev-parse HEAD') echo "${FIXTURE_COMMIT:-75b62b52f53c7823742d5be1e794aed48cad9e2b}" ;;
  *) exit 99 ;;
esac
''')
        self.fixture.stub("sudo", r'''
if [[ "$*" == *build-essential* ]]; then
  echo build-apt-diagnostic
  exit "${FIXTURE_BUILD_APT_RC:-0}"
fi
exit 0
''')
        self.fixture.stub("qmake", r'''
test "$PWD" = "$FIXTURE_SOURCE_DIR"
test "$QT_SELECT" = qt5
test "$*" = '-r librecad.pro CONFIG+=debug_and_release PREFIX=/usr'
touch "$FIXTURE_BUILD_MARKER"
echo qmake-diagnostic
exit "${FIXTURE_QMAKE_RC:-0}"
''')
        self.fixture.stub("make", r'''
test "$PWD" = "$FIXTURE_SOURCE_DIR"
test "$*" = 'release -j2'
echo build-diagnostic
if [ "${FIXTURE_BUILD_RC:-0}" != 0 ]; then exit "$FIXTURE_BUILD_RC"; fi
if [ "${FIXTURE_MISSING_BINARY:-0}" = 1 ]; then exit 0; fi
mkdir -p unix
cp "$FIXTURE_APP" unix/librecad
''')

    def assert_failed(self, **env):
        result, output = self.fixture.run_step("test5", **env)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", output.get("status"))
        self.assertNotIn("installed_version", output)
        values = {**self.fixture.passing(), "steps.test5.outputs.status": output["status"],
                  "steps.test5.outcome": "failure", "steps.test5.conclusion": "success"}
        summary, outputs = self.fixture.run_step("summary", values)
        self.assertNotEqual(0, summary.returncode)
        self.assertEqual("failure", outputs["overall_status"])
        self.assertEqual("1", outputs["core_failed"])
        return result

    def test_existing_exact_appimage_does_not_build_source(self):
        result, output = self.fixture.run_step("test5", FIXTURE_HTTP_STATUS="200", FIXTURE_DOWNLOAD_RC="0")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output["status"])
        self.assertEqual("2.2.1.1", output["installed_version"])
        self.assertIn("official aarch64 AppImage", output["note"])
        self.assertFalse((self.root / "build-started").exists())

    def test_removed_appimage_builds_exact_source_and_runs_full_probe(self):
        result, output = self.fixture.run_step("test5")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output["status"])
        self.assertEqual("2.2.1.1", output["installed_version"])
        self.assertIn("AppImage packaging was not validated", output["note"])
        self.assertTrue((self.root / "build-started").exists())
        proof, = self.root.rglob("window.txt")
        self.assertRegex(proof.read_text(), r"(?m)^window_verified pid=\d+ id=42 title=LibreCAD$")
        version, = self.root.rglob("version.txt")
        self.assertEqual("LibreCAD v2.2.1.1\n", version.read_text())

    def test_wrong_source_selection_fails_before_build(self):
        for env in ({"FIXTURE_ORIGIN": "https://github.com/example/LibreCAD.git"},
                    {"FIXTURE_TAG": "v2.2.1.5"}, {"FIXTURE_COMMIT": "0" * 40}):
            with self.subTest(env=env):
                self.assert_failed(**env)
                self.assertFalse((self.root / "build-started").exists())

    def test_other_download_failures_do_not_fall_back(self):
        for rc, http in (("22", "403"), ("22", "500"), ("6", "000"), ("28", "200"), ("28", "404")):
            with self.subTest(rc=rc, http=http):
                self.assert_failed(FIXTURE_DOWNLOAD_RC=rc, FIXTURE_HTTP_STATUS=http)
                self.assertFalse((self.root / "build-started").exists())

    def test_corrupt_successful_downloads_fail_without_source_fallback(self):
        for env in ({"FIXTURE_CORRUPT_DOWNLOAD": "1"}, {"FIXTURE_IMAGE_ARCH": "x86-64"}):
            with self.subTest(env=env):
                self.assert_failed(FIXTURE_DOWNLOAD_RC="0", FIXTURE_HTTP_STATUS="200", **env)
                self.assertFalse((self.root / "build-started").exists())

    def test_build_timeouts_are_fatal_within_job_budget(self):
        self.assertEqual(45, self.fixture.job["timeout-minutes"])
        command = self.fixture.job["env"]["TEST5_COMMAND"]
        self.assertIn("timeout --kill-after=60s 5m env QT_SELECT=qt5 qmake", command)
        self.assertIn("timeout --kill-after=60s 30m make release -j2", command)
        for env in ({"FIXTURE_QMAKE_TIMEOUT_RC": "124"}, {"FIXTURE_BUILD_TIMEOUT_RC": "124"},
                    {"FIXTURE_BUILD_TIMEOUT_RC": "137"}):
            with self.subTest(env=env):
                result = self.assert_failed(**env)
                self.assertEqual(int(next(iter(env.values()))), result.returncode)

    def test_source_build_failures_are_fatal_and_expose_diagnostics(self):
        for env, diagnostic in (({"FIXTURE_BUILD_APT_RC": "100"}, "build-apt-diagnostic"),
                                ({"FIXTURE_QMAKE_RC": "2"}, "qmake-diagnostic"),
                                ({"FIXTURE_BUILD_RC": "2"}, "build-diagnostic"),
                                ({"FIXTURE_MISSING_BINARY": "1"}, "build-diagnostic")):
            with self.subTest(env=env):
                result = self.assert_failed(**env)
                self.assertIn(diagnostic, result.stdout)

    def test_source_runtime_still_rejects_invalid_arm_cli_and_gui_proof(self):
        for env in ({"FIXTURE_BINARY_ARCH": "x86-64"}, {"FIXTURE_VERSION": "2.2.1.5"},
                    {"FIXTURE_HELP_RC": "134"}, {"FIXTURE_GUI_RC": "0"},
                    {"FIXTURE_GUI_RC": "134"}, {"FIXTURE_WINDOW_PID": "99999999"},
                    {"FIXTURE_WINDOW_CLASS": "unrelated"}):
            with self.subTest(env=env):
                self.assert_failed(**env)


if __name__ == "__main__":
    unittest.main()
