"""Exercise Ruby's actual workflow lookup and fail-closed summary accounting."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-ruby.yml"


class RubyWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ruby-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-ruby"]
        self.steps = {step["id"]: step for step in job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = {**os.environ, "PATH": str(self.bin), "BASELINE_VERSION": "3.4.0",
                    "GITHUB_OUTPUT": str(self.root / "outputs"), "FIXTURE_ROOT": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1"}
        self.stub("ruby", 'print("3.4.0", end="")\n')
        self.stub("python3", '''import io
import os
from pathlib import Path
import sys
import urllib.error
from unittest.mock import patch

root = Path(os.environ["FIXTURE_ROOT"])

def fetch(url, timeout):
    assert url == "https://www.ruby-lang.org/en/downloads/releases/"
    assert timeout == 30
    if os.environ.get("FETCH_ERROR"):
        raise urllib.error.URLError("fixture network failure")
    return io.BytesIO((root / "releases.html").read_bytes())

with patch("urllib.request.urlopen", fetch):
    exec(compile(sys.stdin.read(), "actual-ruby-workflow-lookup", "exec"), {"__name__": "__main__"})
''')

    def stub(self, name, code):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n{code}")
        path.chmod(0o755)

    def document(self, versions=(), extra=""):
        links = "".join(
            f'<a href="https://cache.ruby-lang.org/pub/ruby/{version.rsplit(".", 1)[0]}/ruby-{version}.tar.gz">download</a>'
            for version in versions
        )
        (self.root / "releases.html").write_text(f"<html><body>{links}{extra}</body></html>")

    def run_step(self, step, values=None, **environment):
        values = {"steps.install.outputs.ruby_bin": str(self.bin / "ruby"), **(values or {})}

        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term.strip("'")
                if term.isdigit():
                    return term
                if values.get(term):
                    return values[term]
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["/bin/bash", "-euo", "pipefail", "-c", script],
                                env={**self.env, **environment}, capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_preview_does_not_become_a_nonexistent_stable_release(self):
        self.document(["4.1.0-preview1", "3.4.11", "4.0.7", "3.4.0"],
                      extra="<p>Ruby 4.1.0-preview1</p>")
        result, outputs = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"version": "3.4.0", "latest": "4.0.7"}, outputs)

    def test_all_prerelease_suffixes_are_excluded(self):
        for suffix in ("-preview1", "-rc1", "rc1", "-alpha1", "-beta1", "-dev"):
            with self.subTest(suffix=suffix):
                self.document(["4.0.7", "4.1.0" + suffix])
                result, outputs = self.run_step("version")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("4.0.7", outputs["latest"])

    def test_numeric_order_and_duplicates(self):
        self.document(["4.0.9", "3.4.11", "4.0.10", "4.0.8", "4.0.10"])
        result, outputs = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("4.0.10", outputs["latest"])

    def test_real_stable_release_is_selected_when_published(self):
        self.document(["4.0.7", "4.1.0-preview1", "4.1.0", "4.2.0-rc1"])
        result, outputs = self.run_step("version")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("4.1.0", outputs["latest"])

    def test_unrelated_links_comments_and_text_do_not_define_releases(self):
        archive = "https://cache.ruby-lang.org/pub/ruby/9.0/ruby-9.0.0.tar.gz"
        for extra in ("Ruby 9.0.0", f'<!-- <a href="{archive}">download</a> -->',
                      f'<script>const url = \'<a href="{archive}">download</a>\';</script>',
                      f'<a href="{archive.replace("cache.ruby-lang.org", "example.invalid")}">Ruby 9.0.0</a>',
                      f'<a href="{archive.replace("/9.0/", "/8.0/")}">download</a>',
                      f'<a href="{archive}?preview=1">download</a>',
                      f'<a href="{archive}" href="invalid">download</a>'):
            with self.subTest(extra=extra):
                self.document(["4.0.7"], extra=extra)
                result, outputs = self.run_step("version")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("4.0.7", outputs["latest"])

    def test_empty_preview_only_malformed_and_oversized_index_fail(self):
        for content in (b"", b"<html></html>", b"Ruby 4.1.0-preview1", b"\xff", b"x" * 2_000_001):
            with self.subTest(content=content[:30]):
                (self.root / "releases.html").write_bytes(content)
                result, outputs = self.run_step("version")
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("latest", outputs)
        self.document(["4.1.0-preview1", "4.1.0-rc1"])
        result, outputs = self.run_step("version")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("latest", outputs)

    def test_network_failure_does_not_fall_back_to_baseline(self):
        self.document(["4.0.7"])
        result, outputs = self.run_step("version", FETCH_ERROR="1")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("latest", outputs)

    def test_summary_requires_all_six_tests_and_counts_missing_regression_as_failure(self):
        values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
        result, outputs = self.run_step("summary", values)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("6", "0", "success"), tuple(outputs[k] for k in ("passed", "failed", "overall_status")))
        for status in ("failed", "skipped", ""):
            with self.subTest(status=status):
                result, outputs = self.run_step("summary", {**values, "steps.test6.outputs.status": status})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("5", "1", "failure"), tuple(outputs[k] for k in ("passed", "failed", "overall_status")))


if __name__ == "__main__":
    unittest.main()
