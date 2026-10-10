"""Exercise MinIO's real workflow discovery, candidate checks, and final gates."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-minio-mc.yml"
BASELINE = "2017-02-02T22:38:48Z"
NEXT_VERSION = "2017-02-06T20:16:19Z"
BASELINE_MAIN_HELP = """NAME:
  mc - Minio Client for cloud storage and filesystems.
USAGE:
  mc [FLAGS] COMMAND [COMMAND FLAGS | -h] [ARGUMENTS...]
COMMANDS:
  ls       List files and folders.
"""
BASELINE_LS_HELP = """NAME:
   mc ls - List files and folders.
USAGE:
   mc ls [FLAGS] TARGET [TARGET ...]
FLAGS:
  --recursive, -r                  List recursively.
"""


class MinioMcWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="minio-mc-contract-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-minio-mc"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.root), TMPDIR=str(self.root),
                        RUNNER_TEMP=str(self.root), GITHUB_OUTPUT=str(self.root / "output"),
                        GITHUB_PATH=str(self.root / "path"), GH_TOKEN="unit-test-token",
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        PYTHONDONTWRITEBYTECODE="1", FIXTURE_ROOT=str(self.root))
        self.values = {"steps.metadata.outputs.current_version": BASELINE,
                       "steps.version.outputs.version": BASELINE}
        for number in range(1, 7):
            self.values[f"steps.test{number}.outputs.status"] = "passed"
            self.values[f"steps.test{number}.outputs.duration"] = str(number)
        self.candidate = self.root / "candidate"
        self.candidate.write_text('''#!/bin/bash
if [ "${GH_TOKEN+x}" = x ]; then
  echo "Unexpected authentication environment" >&2
  exit 97
fi
printf '%s\\n' "$1" >> "$FIXTURE_ROOT/binary-calls"
if [ "$1" = --version ]; then
  printf '%s\n' "${FIXTURE_VERSION-mc version RELEASE.2017-02-06T20:16:19Z}"
  exit "${FIXTURE_VERSION_EXIT:-0}"
fi
if [ "$1" = --help ]; then
  printf '%s\n' "${FIXTURE_HELP-NAME:
  mc
USAGE:
  mc command
COMMANDS:
  ls}"
  exit "${FIXTURE_HELP_EXIT:-0}"
fi
exit 1
''')
        self.digest = hashlib.sha256(self.candidate.read_bytes()).hexdigest()
        self.pages = [[self.release(NEXT_VERSION), self.release(BASELINE)]]
        self.executable("python3", f"#!{sys.executable}\n" + '''
import io
import json
import os
from email.message import Message
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
import sys

root = Path(os.environ["FIXTURE_ROOT"])
class FixtureTransport(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
    def http_open(self, request):
        with (root / "requests").open("a") as stream:
            stream.write(request.full_url + "\\n")
        assert request.headers["Authorization"] == "Bearer unit-test-token"
        assert request.timeout == 30
        headers = Message()
        if os.environ.get("FIXTURE_REDIRECT"):
            headers["Location"] = os.environ["FIXTURE_REDIRECT"]
            response = urllib.response.addinfourl(io.BytesIO(b"redirect"), headers,
                request.full_url, int(os.environ.get("FIXTURE_REDIRECT_CODE", "302")))
            response.msg = "Found"
            return response
        if os.environ.get("FIXTURE_LOOKUP_FAIL"):
            raise urllib.error.HTTPError(request.full_url, 403, "fixture rate limit", {}, None)
        page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["page"][0])
        pages = json.loads((root / "pages.json").read_text())
        if os.environ.get("FIXTURE_REPEAT_PAGE"):
            page = 1
        response = urllib.response.addinfourl(io.BytesIO(json.dumps(pages[page - 1]).encode()),
                                             headers, request.full_url, 200)
        response.msg = "OK"
        return response
    https_open = http_open

build_opener = urllib.request.build_opener
urllib.request.build_opener = lambda *handlers: build_opener(FixtureTransport(), *handlers)
sys.argv = sys.argv[1:]
exec(compile(sys.stdin.read(), "workflow-release-discovery", "exec"))
''')
        self.executable("curl", f"#!{sys.executable}\n" + '''
import os
from pathlib import Path
import sys

root = Path(os.environ["FIXTURE_ROOT"])
if os.environ.get("FIXTURE_REQUIRE_NO_TOKEN"):
    assert "GH_TOKEN" not in os.environ, "Authentication environment reached curl"
    (root / "curl-token-absent").touch()
if os.environ.get("FIXTURE_DOWNLOAD_FAIL"):
    raise SystemExit(22)
destination = Path(sys.argv[sys.argv.index("-o") + 1])
data = (root / "candidate").read_bytes()
destination.write_bytes(b"corrupt" if os.environ.get("FIXTURE_CORRUPT") else data)
(root / "download-url").write_text(sys.argv[-1])
''')
        self.executable("file", '#!/bin/bash\nprintf "%s\\n" "${FIXTURE_ARCH:-ELF 64-bit LSB executable, ARM aarch64}"\n')
        # macOS sha256sum does not implement GNU's stdin check mode.
        self.executable("sha256sum", f"#!{sys.executable}\n" + '''
import hashlib
from pathlib import Path
import sys

assert sys.argv[1:] == ["-c"]
expected, path = sys.stdin.read().rstrip("\\n").split("  ", 1)
valid = hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
print(path + (": OK" if valid else ": FAILED"))
raise SystemExit(0 if valid else 1)
''')

    def executable(self, name, script):
        path = self.bin / name
        path.write_text(script)
        path.chmod(0o755)

    def baseline_help_fixture(self):
        self.env.update(FIXTURE_MAIN_HELP=BASELINE_MAIN_HELP, FIXTURE_LS_HELP=BASELINE_LS_HELP)
        self.executable("mc", '''#!/bin/bash
printf '%s\\n' "$*" >> "$FIXTURE_ROOT/baseline-calls"
case "$*" in
  --help) HELP="$FIXTURE_MAIN_HELP" ;;
  "ls --help") HELP="$FIXTURE_LS_HELP" ;;
  *) exit 64 ;;
esac
printf '%s\\n' "${FIXTURE_BASELINE_HELP-$HELP}"
exit "${FIXTURE_BASELINE_EXIT:-0}"
''')
        self.executable("uname", '''#!/bin/bash
[ "$*" = -m ] || exit 64
printf '%s\\n' "${FIXTURE_BASELINE_ARCH:-aarch64}"
''')

    def assert_baseline_failed(self, result, outputs):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "failed")
        self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def release(self, version, **updates):
        tag = "RELEASE." + version.replace(":", "-")
        name = "mc.linux-arm64." + tag
        result = {"tag_name": tag, "draft": False, "prerelease": False,
                  "assets": [{"name": name, "state": "uploaded", "size": 123,
                              "digest": "sha256:" + self.digest,
                              "browser_download_url": f"https://github.com/minio/mc/releases/download/{tag}/{name}"}]}
        result.update(updates)
        return result

    def render(self, script):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if self.values.get(term):
                    return self.values[term]
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)

    def run_step(self, step_id, **env):
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        (self.root / "pages.json").write_text(json.dumps(self.pages))
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.render(self.steps[step_id]["run"])],
            cwd=self.root, env={**self.env, "FIXTURE_REQUIRE_NO_TOKEN": "1" if step_id == "test6" else "", **env},
            capture_output=True, text=True, timeout=30)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        self.assertNotIn("unit-test-token", result.stdout + result.stderr + output.read_text())
        return result, outputs

    def assert_failed(self, result, outputs, decision):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "failed")
        self.assertEqual(outputs["decision"], decision)
        self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_baseline_and_all_six_probes_remain(self):
        self.assertIn(f"current_version={BASELINE}", self.steps["metadata"]["run"])
        self.assertEqual([key for key in self.steps if re.fullmatch(r"test[1-6]", key)],
                         [f"test{i}" for i in range(1, 7)])
        install = self.steps["install"]["run"]
        self.assertIn("4f7aad07a483a3d11428e3e2af8105fdf1ca9e65a11cfedc2cbd5efb7f3e52b6", install)
        self.assertIn('"$GITHUB_PATH"', install)
        self.assertNotIn("/usr/local/bin", install)
        self.assertNotIn("dl.min.io", WORKFLOW.read_text())
        self.assertEqual(self.steps["test6"]["env"]["GH_TOKEN"], "${{ github.token }}")
        self.assertIn('config host add local http://127.0.0.1:9000', self.steps["test4"]["run"])
        self.assertIn('config host list | grep -q "local"', self.steps["test4"]["run"])
        self.assertIn("mc ls --help", self.steps["test5"]["run"])

    def test_selects_earliest_stable_arm64_across_pages(self):
        ignored = self.release("2017-02-03T00:00:00Z", draft=True)
        self.pages = [[self.release("2017-02-10T00:00:00Z")] + [ignored] * 99,
                      [self.release(NEXT_VERSION), self.release(BASELINE),
                       self.release("2017-02-04T00:00:00Z", prerelease=True),
                       self.release("2017-02-05T00:00:00Z", assets=[])]]
        result, outputs = self.run_step("test6")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "passed")
        self.assertEqual(outputs["latest_version"], NEXT_VERSION)
        self.assertEqual(outputs["next_installed_version"], NEXT_VERSION)
        self.assertEqual(outputs["decision"], "next_install_validated")
        self.assertEqual((self.root / "download-url").read_text(),
                         self.release(NEXT_VERSION)["assets"][0]["browser_download_url"])
        self.assertEqual(len((self.root / "requests").read_text().splitlines()), 2)

    def test_lookup_errors_never_become_no_newer_release(self):
        for pages, env in ((self.pages, {"FIXTURE_LOOKUP_FAIL": "1"}),
                           ([{"message": "rate limit exceeded"}], {}), ([[]], {}),
                           ([[{"tag_name": "broken"}]], {})):
            with self.subTest(pages=pages, env=env):
                self.pages = pages
                self.assert_failed(*self.run_step("test6", **env), "next_lookup_failed")

    def test_incomplete_pagination_is_failure(self):
        self.pages = [[self.release(NEXT_VERSION)] * 100]
        self.assert_failed(*self.run_step("test6", FIXTURE_REPEAT_PAGE="1"), "next_lookup_failed")

    def test_token_is_removed_before_download_and_both_binary_calls(self):
        result, outputs = self.run_step("test6")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(outputs["status"], "passed")
        self.assertTrue((self.root / "curl-token-absent").exists())
        self.assertEqual((self.root / "binary-calls").read_text().splitlines(), ["--version", "--help"])

    def test_redirects_are_rejected_without_a_second_authenticated_request(self):
        for code in (301, 302, 303, 307, 308):
            for target in ("https://outside.invalid/releases", "http://api.github.com/releases",
                           "https://api.github.com/same-host-redirect"):
                with self.subTest(code=code, target=target):
                    requests = self.root / "requests"
                    requests.write_text("")
                    result, outputs = self.run_step("test6", FIXTURE_REDIRECT=target,
                                                    FIXTURE_REDIRECT_CODE=str(code))
                    self.assert_failed(result, outputs, "next_lookup_failed")
                    self.assertEqual(requests.read_text().splitlines(),
                                     ["https://api.github.com/repos/minio/mc/releases?per_page=100&page=1"])
                    self.assertFalse((self.root / "download-url").exists())

    def test_malformed_later_page_flags_fail_instead_of_skipping_newer_release(self):
        for field in ("draft", "prerelease"):
            for value in ("false", "true", 0, 1, None, [], {}):
                with self.subTest(field=field, value=value):
                    self.pages = [[self.release(BASELINE)] * 100,
                                  [self.release(NEXT_VERSION, **{field: value})]]
                    self.assert_failed(*self.run_step("test6"), "next_lookup_failed")
                    self.assertFalse((self.root / "download-url").exists())

    def test_missing_or_untrusted_arm64_asset_is_failure(self):
        for field, value in (("name", "mc.linux-amd64.RELEASE.wrong"),
                             ("name", self.release(NEXT_VERSION)["assets"][0]["name"] + ".asc"),
                             ("browser_download_url", "https://example.invalid/mc"),
                             ("state", "new"), ("size", 0), ("digest", None)):
            with self.subTest(field=field, value=value):
                candidate = self.release(NEXT_VERSION)
                candidate["assets"][0][field] = value
                self.pages = [[candidate, self.release(BASELINE)]]
                self.assert_failed(*self.run_step("test6"), "next_lookup_failed")

    def test_complete_lookup_with_no_newer_release_preserves_skip(self):
        self.pages = [[self.release(BASELINE)]]
        result, outputs = self.run_step("test6")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["status"], "skipped")
        self.assertEqual(outputs["decision"], "no_newer_stable_available")
        self.assertEqual(outputs["next_installed_version"], "not_installed")
        self.assertFalse((self.root / "download-url").exists())

    def test_download_and_checksum_failures_are_terminal(self):
        for env in ("FIXTURE_DOWNLOAD_FAIL", "FIXTURE_CORRUPT"):
            with self.subTest(env=env):
                result, outputs = self.run_step("test6", **{env: "1"})
                self.assert_failed(result, outputs, "next_install_failed")
                self.assertEqual(outputs["next_installed_version"], "not_installed")

    def test_baseline_download_and_checksum_cannot_report_install_success(self):
        bootstrap = self.root / ".github/actions/apt-bootstrap/bootstrap.sh"
        bootstrap.parent.mkdir(parents=True)
        bootstrap.write_text("#!/bin/bash\nexit 0\n")
        for env in ({"FIXTURE_DOWNLOAD_FAIL": "1"}, {}):
            with self.subTest(env=env):
                result, outputs = self.run_step("install", **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(outputs.get("install_status"), "success")
                self.assertFalse(Path(self.env["GITHUB_PATH"]).exists())

    def test_baseline_help_positive_commands_and_outputs(self):
        self.baseline_help_fixture()
        for step in ("test3", "test5"):
            with self.subTest(step=step):
                result, outputs = self.run_step(step)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(outputs["status"], "passed")
                self.assertRegex(outputs["duration"], r"^[0-9]+$")
        self.assertEqual((self.root / "baseline-calls").read_text().splitlines(),
                         ["--help", "ls --help"])

    def test_baseline_nonzero_help_exit_fails_with_error_or_valid_sections(self):
        self.baseline_help_fixture()
        for step in ("test3", "test5"):
            for env in ({"FIXTURE_BASELINE_EXIT": "17", "FIXTURE_BASELINE_HELP": "mc ls:<ERROR> failed to initialize"},
                        {"FIXTURE_BASELINE_EXIT": "1", "FIXTURE_BASELINE_HELP": "mc:<ERROR> failed to initialize"},
                        {"FIXTURE_BASELINE_EXIT": "17"}):
                with self.subTest(step=step, env=env):
                    self.assert_baseline_failed(*self.run_step(step, **env))

    def test_baseline_successful_error_or_incomplete_help_is_not_a_pass(self):
        self.baseline_help_fixture()
        cases = {
            "test3": ["mc:<ERROR> failed to initialize", "NAME: mc", "USAGE: mc", "COMMANDS: ls"],
            "test5": ["mc ls:<ERROR> failed to initialize", "list objects files", BASELINE_MAIN_HELP,
                      "USAGE:\n  mc ls [FLAGS] TARGET", "FLAGS:\n  mc ls --recursive",
                      "USAGE:\n  mc cp [FLAGS] TARGET\nFLAGS:\n  --recursive"],
        }
        for step, help_outputs in cases.items():
            for help_output in help_outputs:
                with self.subTest(step=step, help_output=help_output):
                    self.assert_baseline_failed(*self.run_step(step, FIXTURE_BASELINE_HELP=help_output))

    def test_baseline_ls_help_still_requires_arm64(self):
        self.baseline_help_fixture()
        self.assert_baseline_failed(*self.run_step("test5", FIXTURE_BASELINE_ARCH="x86_64"))
        self.assertEqual((self.root / "baseline-calls").read_text().splitlines(), ["ls --help"])

    def test_actual_baseline_help_failure_reaches_final_gate(self):
        self.baseline_help_fixture()
        for step in ("test3", "test5"):
            with self.subTest(step=step):
                result, outputs = self.run_step(step, FIXTURE_BASELINE_EXIT="17",
                                                FIXTURE_BASELINE_HELP="mc ls:<ERROR> failed to initialize")
                self.assert_baseline_failed(result, outputs)
                status_key = f"steps.{step}.outputs.status"
                self.values[status_key] = outputs["status"]
                result, summary = self.run_step("summary")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(summary["failed"], "1")
                self.assertEqual(summary["core_failed"], "1")
                self.assertEqual(summary["overall_status"], "failure")
                self.assertEqual(summary["badge_status"], "failing")
                self.values[status_key] = "passed"

    def test_wrong_architecture_version_and_help_cannot_pass(self):
        for env in ({"FIXTURE_ARCH": "ELF 64-bit LSB executable, x86-64"},
                    {"FIXTURE_VERSION": "mc version RELEASE.2017-02-02T22:38:48Z"},
                    {"FIXTURE_VERSION": ""}, {"FIXTURE_VERSION_EXIT": "1"},
                    {"FIXTURE_HELP": "invalid"}):
            with self.subTest(env=env):
                result, outputs = self.run_step("test6", **env)
                self.assert_failed(result, outputs, "next_install_failed")
                if "FIXTURE_VERSION" in env or "FIXTURE_VERSION_EXIT" in env:
                    self.assertNotEqual(outputs["next_installed_version"], NEXT_VERSION)

    def test_candidate_help_requires_success_and_real_sections(self):
        for env in ({"FIXTURE_HELP": "mc: <ERROR> request failed", "FIXTURE_HELP_EXIT": "1"},
                    {"FIXTURE_HELP": "mc: <ERROR> request failed"},
                    {"FIXTURE_HELP_EXIT": "1"},
                    {"FIXTURE_HELP": "USAGE: mc command"},
                    {"FIXTURE_HELP": "COMMANDS: ls"}):
            with self.subTest(env=env):
                self.assert_failed(*self.run_step("test6", **env), "next_install_failed")

    def test_six_passes_and_every_failure_reach_the_final_gate(self):
        result, outputs = self.run_step("summary")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["passed"], "6")
        self.assertEqual(outputs["duration"], "21")
        self.assertEqual(outputs["overall_status"], "success")
        for number in range(1, 7):
            key = f"steps.test{number}.outputs.status"
            for status in (("failed", "") if number < 6 else ("failed",)):
                with self.subTest(number=number, status=status):
                    self.values[key] = status
                    result, outputs = self.run_step("summary")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(outputs["failed"], "1")
                    self.assertEqual(outputs["overall_status"], "failure")
                    self.assertEqual(outputs["badge_status"], "failing")
            self.values[key] = "passed"

    def test_all_shell_steps_parse(self):
        for step_id, step in self.steps.items():
            with self.subTest(step_id=step_id):
                result = subprocess.run(["bash", "-n"], input=self.render(step["run"]),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
