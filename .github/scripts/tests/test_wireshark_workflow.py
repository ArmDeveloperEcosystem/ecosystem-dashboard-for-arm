"""Execute Wireshark's actual discovery fragment and Test 6 decision branches."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-wireshark.yml"
BASELINE = "4.6.6"


class WiresharkWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wireshark-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-wireshark"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for tool in ("awk", "cat", "date", "mkdir", "rm"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.env = {**os.environ, "PATH": str(self.bin), "HOME": str(self.root),
                    "TMPDIR": str(self.root), "RUNNER_TEMP": str(self.root),
                    "GITHUB_OUTPUT": str(self.root / "outputs"), "FIXTURE_ROOT": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1", "WIRESHARK_VERSION": BASELINE}
        self.stub(self.bin / "python3", '''import email.message
import http.client
import io
import os
from pathlib import Path
import sys
import urllib.error
from unittest.mock import patch

root = Path(os.environ["FIXTURE_ROOT"])
mode = os.environ.get("FETCH_MODE", "ok")

class Response(io.BytesIO):
    status = int(os.environ.get("HTTP_STATUS", "200"))
    headers = email.message.Message()
    headers["Content-Type"] = os.environ.get("CONTENT_TYPE", "text/html; charset=UTF-8")
    if "CONTENT_LENGTH" in os.environ:
        headers["Content-Length"] = os.environ["CONTENT_LENGTH"]

    def geturl(self):
        return os.environ.get("FINAL_URL", "https://www.wireshark.org/download/src/all-versions/")

    def read(self, size=-1):
        assert size == 2_000_001
        if mode == "incomplete":
            raise http.client.IncompleteRead(b"<html><body>partial")
        return super().read(size)

def fetch(url, timeout):
    assert url == "https://www.wireshark.org/download/src/all-versions/"
    assert timeout == 20
    (root / "requested-url").write_text(url)
    if mode == "http":
        raise urllib.error.HTTPError(url, 503, "fixture unavailable", {}, None)
    if mode == "dns":
        raise urllib.error.URLError("fixture DNS failure")
    if mode == "timeout":
        raise TimeoutError("fixture timeout\\nwith a second line")
    return Response((root / "index.html").read_bytes())

with patch("urllib.request.urlopen", fetch):
    exec(compile(sys.stdin.read(), "actual-workflow-discovery", "exec"), {"__name__": "__main__"})
''')
        source = self.root / "source/build/run"
        source.mkdir(parents=True)
        self.stub(source / "tshark", '''import os
print("TShark (Wireshark) " + os.environ.get("REPORTED_VERSION", "4.6.6"))
''')
        self.stub(self.bin / "bash", '''import json
import os
from pathlib import Path
import sys
Path(os.environ["FIXTURE_ROOT"], "download-args.json").write_text(json.dumps(sys.argv[1:]))
sys.exit(73)
''')
        self.index([BASELINE])

    def stub(self, path, source):
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    def index(self, versions, extra=""):
        anchors = "".join(f'<a href="wireshark-{version}.tar.xz">archive</a>' for version in versions)
        self.document(f"<html><head><title>Index</title></head><body>{anchors}{extra}</body></html>")

    def document(self, source):
        (self.root / "index.html").write_bytes(source.encode() if isinstance(source, str) else source)

    def run_step(self, name, version_outputs=None, **environment):
        values = {"steps.install.outputs.source_dir": str(self.root / "source"),
                  "env.WIRESHARK_VERSION": BASELINE,
                  **{f"steps.version.outputs.{key}": value for key, value in (version_outputs or {}).items()}}

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term.strip("'")
                if values.get(term):
                    return values[term]
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[name]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["/bin/bash", "-euo", "pipefail", "-c", script], cwd=self.root,
            env={**self.env, "WIRESHARK_LOOKUP_ERROR": (version_outputs or {}).get("lookup_error", ""), **environment},
            capture_output=True, text=True, timeout=15,
        )
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def lookup(self, **environment):
        result, outputs = self.run_step("version", **environment)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return outputs

    def assert_lookup_failed(self, **environment):
        outputs = self.lookup(**environment)
        self.assertEqual("unknown", outputs["latest"])
        self.assertTrue(outputs["lookup_error"])
        self.assertNotIn("\n", outputs["lookup_error"])
        result, regression = self.run_step("test6", outputs)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(("failed", "next_lookup_failed", "lookup_failed"),
                         tuple(regression[key] for key in ("status", "decision", "next_installed_version")))
        self.assertIn(outputs["lookup_error"], regression["comparison"])
        self.assertRegex(regression["duration"], r"^[0-9]+$")
        self.assertFalse((self.root / "download-args.json").exists())

    def test_baseline_only_index_proves_no_newer_release(self):
        outputs = self.lookup()
        self.assertEqual(BASELINE, outputs["version"])
        self.assertEqual(BASELINE, outputs["latest"])
        self.assertEqual("", outputs["lookup_error"])
        result, regression = self.run_step("test6", outputs)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("skipped", "no_newer_stable_available", BASELINE),
                         tuple(regression[key] for key in ("status", "decision", "next_installed_version")))

    def test_ordinary_newer_filename_reaches_candidate_download_not_skip(self):
        self.index([BASELINE, "4.6.8"])
        outputs = self.lookup()
        self.assertEqual("4.6.8", outputs["latest"])
        result, regression = self.run_step("test6", outputs)
        self.assertEqual(73, result.returncode)
        self.assertNotIn("decision", regression)
        self.assertNotIn("status", regression)
        arguments = (self.root / "download-args.json").read_text()
        self.assertIn("download-with-fallback.sh", arguments)
        self.assertIn("https://www.wireshark.org/download/src/wireshark-4.6.8.tar.xz", arguments)

    def test_first_next_stable_is_numeric_not_latest_or_development(self):
        self.index(["4.8.0", "4.6.10", "4.7.0", "4.4.18", "4.6.8", "4.6.8", "latest"])
        self.assertEqual("4.6.8", self.lookup()["latest"])

    def test_archived_intervening_stable_precedes_current_index_release(self):
        self.index(["4.4.18", "4.6.8", "4.7.2", "4.7.3", "latest", BASELINE, "4.6.7"])
        outputs = self.lookup()
        self.assertEqual("https://www.wireshark.org/download/src/all-versions/",
                         (self.root / "requested-url").read_text())
        self.assertEqual("4.6.7", outputs["latest"])
        result, regression = self.run_step("test6", outputs)
        self.assertEqual(73, result.returncode)
        self.assertNotIn("status", regression)
        self.assertIn("https://www.wireshark.org/download/src/all-versions/wireshark-4.6.7.tar.xz",
                      (self.root / "download-args.json").read_text())

    def test_prerelease_filenames_do_not_poison_stable_discovery(self):
        prereleases = ["4.7.0rc1", "4.6.0rc1", "4.8.0rc2", "4.6.8-rc1", "4.8.0alpha1", "4.8.0beta2"]
        for stable, expected in (([BASELINE], BASELINE), ([BASELINE, "4.6.8"], "4.6.8")):
            with self.subTest(stable=stable):
                self.index(prereleases + stable)
                self.assertEqual(expected, self.lookup()["latest"])
        self.index(prereleases)
        self.assert_lookup_failed()

    def test_legal_omitted_html_and_table_closing_tags_are_accepted(self):
        self.document('<!doctype html><html><body><table><tr><td><a href="wireshark-4.6.6.tar.xz">baseline</a>'
                      '<tr><td><a href="wireshark-4.6.8.tar.xz">newer</a></table>')
        self.assertEqual("4.6.8", self.lookup()["latest"])

    def test_supported_relative_root_and_absolute_hrefs(self):
        for href in ("./wireshark-4.6.8.tar.xz", "/download/src/all-versions/wireshark-4.6.8.tar.xz",
                     "https://www.wireshark.org/download/src/all-versions/wireshark-4.6.8.tar.xz"):
            with self.subTest(href=href):
                self.index([BASELINE], f'<a href="{href}">unrelated label</a>')
                self.assertEqual("4.6.8", self.lookup()["latest"])

    def test_visible_text_comments_scripts_and_unrelated_links_are_not_releases(self):
        self.index([BASELINE], '''wireshark-9.0.0.tar.xz
<!-- <a href="wireshark-9.0.0.tar.xz">comment</a> -->
<script>const text = '<a href="wireshark-9.0.0.tar.xz">script</a>';</script>
<a href="https://example.invalid/wireshark-9.0.0.tar.xz">foreign host</a>
<a href="all-versions/wireshark-9.0.0.tar.xz">other directory</a>
<a href="?file=wireshark-9.0.0.tar.xz">query</a>''')
        self.assertEqual(BASELINE, self.lookup()["latest"])

    def test_invalid_release_versions_fail_even_with_a_valid_baseline(self):
        for version in ("4.06.8", "4.6", "v4.6.8", "4.6.bad", "4.6.8rcbad", "4.6.8;echo bad", "-4.6.8"):
            with self.subTest(version=version):
                self.index([BASELINE, version])
                self.assert_lookup_failed()

    def test_invalid_or_unstable_current_versions_fail_closed(self):
        for version in ("", "unknown", "4.6", "v4.6.6", "4.06.6", "4.6.6-rc1", "4.7.0"):
            with self.subTest(version=version):
                self.assert_lookup_failed(REPORTED_VERSION=version)

    def test_empty_malformed_truncated_and_non_html_documents_fail_closed(self):
        for source in (b"", b"\xff", "wireshark-4.6.6.tar.xz", "<html><body></body></html>",
                       '<html><body><a href="wireshark-4.6.6.tar.xz',
                       '<a href="wireshark-4.6.6.tar.xz">baseline</a><a href="wireshark-4.6.8',
                       '<a>wireshark-4.6.6.tar.xz</a>',
                       '<html><body><a href="wireshark-4.6.6.tar.xz" href="bad">baseline</a></body></html>'):
            with self.subTest(source=source):
                self.document(source)
                self.assert_lookup_failed()

    def test_absent_baseline_and_no_newer_stable_is_not_no_newer_proof(self):
        for versions in (["4.4.18"], ["4.7.0"], ["latest"], []):
            with self.subTest(versions=versions):
                self.index(versions)
                self.assert_lookup_failed()

    def test_http_dns_timeout_and_incomplete_read_errors_fail_closed(self):
        for mode in ("http", "dns", "timeout", "incomplete"):
            with self.subTest(mode=mode):
                self.assert_lookup_failed(FETCH_MODE=mode)

    def test_unexpected_http_status_or_content_type_fails_closed(self):
        for environment in ({"HTTP_STATUS": "204"}, {"HTTP_STATUS": "206"},
                            {"CONTENT_TYPE": "application/json"}, {"CONTENT_TYPE": "text/plain"}):
            with self.subTest(environment=environment):
                self.assert_lookup_failed(**environment)

    def test_redirected_index_and_truncated_response_fail_closed(self):
        for environment in ({"FINAL_URL": "https://example.invalid/download/src/"},
                            {"FINAL_URL": "http://www.wireshark.org/download/src/"},
                            {"FINAL_URL": "https://www.wireshark.org/error.html"},
                            {"CONTENT_LENGTH": "999999"}, {"CONTENT_LENGTH": "invalid"}):
            with self.subTest(environment=environment):
                self.assert_lookup_failed(**environment)

    def test_oversized_index_is_not_parsed_as_partial_success(self):
        self.document((self.root / "index.html").read_bytes() + b" " * 2_000_001)
        self.assert_lookup_failed()

    def test_missing_python_reaches_lookup_failed_without_fallback(self):
        (self.bin / "python3").unlink()
        self.assert_lookup_failed()

    def test_pinned_baseline_and_real_build_arm_and_pcap_checks_are_preserved(self):
        self.assertEqual(BASELINE, self.job["env"]["WIRESHARK_VERSION"])
        for name in ("install", "test6"):
            script = self.steps[name]["run"]
            for command in ("download-with-fallback.sh", "cmake -S", "cmake --build", "--target tshark capinfos",
                            "-DBUILD_wireshark=OFF -DBUILD_tshark=ON -DENABLE_QT6=OFF"):
                self.assertIn(command, script)
        self.assertIn('"$VERSION" = "${WIRESHARK_VERSION}"', self.steps["test2"]["run"])
        self.assertIn('"$(uname -m)" = "aarch64"', self.steps["test4"]["run"])
        self.assertIn('file "$SRC_DIR/build/run/tshark"', self.steps["test4"]["run"])
        for name, prefix, pcap in (("test5", "SRC_DIR", "empty.pcap"), ("test6", "NEXT_SRC", "empty-next.pcap")):
            script = self.steps[name]["run"]
            self.assertIn(f'"${prefix}/build/run/capinfos" /tmp/{pcap}', script)
            self.assertIn(f'"${prefix}/build/run/tshark" -r /tmp/{pcap}', script)
        self.assertIn('[ "$NEXT_REPORTED" = "$LATEST" ]', self.steps["test6"]["run"])


if __name__ == "__main__":
    unittest.main()
