"""Execute Drupal's workflow discovery, real archive checks, and result accounting."""

import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-drupal.yml"
BASELINE = "10.2.4"
CANDIDATE = "11.4.6"
MARKERS = ("index.php", "core/lib/Drupal.php", "composer.json", "core/modules/system/system.module")


class DrupalWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="drupal-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-drupal"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for tool in ("date", "tar", "gzip", "mv"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        (self.bin / "python3").symlink_to(sys.executable)
        self.env = {**os.environ, "PATH": str(self.bin), "HOME": str(self.root),
                    "TMPDIR": str(self.root), "GITHUB_WORKSPACE": str(self.root),
                    "GITHUB_OUTPUT": str(self.root / "outputs"), "FIXTURE_ROOT": str(self.root),
                    "PYTHONDONTWRITEBYTECODE": "1"}
        self.stub("uname", 'import os\nprint(os.environ.get("TEST_ARCH", "aarch64"))\n')
        # BSD mktemp without a template does not honor TMPDIR like GNU mktemp.
        self.stub("mktemp", '''import os, sys, tempfile
assert sys.argv[1:] == ["-d"]
print(tempfile.mkdtemp(prefix="tmp.", dir=os.environ["FIXTURE_ROOT"]))
''')
        self.stub("bash", '''import sys
assert sys.argv[1:] == [".github/actions/apt-bootstrap/bootstrap.sh", "--packages", "curl python3"]
''')
        self.stub("curl", '''import json
import os
from pathlib import Path
import sys

root = Path(os.environ["FIXTURE_ROOT"])
args = sys.argv[1:]
url = args[-1]
with (root / "requests").open("a") as log:
    log.write(json.dumps(args) + "\\n")
output = Path(args[args.index("-o") + 1])
if url == "https://updates.drupal.org/release-history/drupal/current":
    assert "--max-time" in args and args[args.index("--max-time") + 1] == "60"
    output.write_bytes((root / "feed.xml").read_bytes())
    code = int(os.environ.get("LOOKUP_EXIT", "0"))
elif url.startswith("https://ftp.drupal.org/files/projects/drupal-"):
    if os.environ.get("CORRUPT_ARCHIVE"):
        output.write_bytes(b"not a tar archive")
    else:
        output.write_bytes((root / url.rsplit("/", 1)[1]).read_bytes())
    code = int(os.environ.get("ARCHIVE_EXIT", "0"))
else:
    raise AssertionError(url)
if code:
    print(f"curl fixture failure: {code}", file=sys.stderr)
sys.exit(code)
''')
        self.feed(["12.0.0-alpha1", CANDIDATE, "11.4.x-dev", "dev-main", "8.0-alpha2", BASELINE])
        self.archive(BASELINE)
        self.archive(CANDIDATE)

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n{source}")
        path.chmod(0o755)

    def feed(self, versions):
        project = ET.Element("project")
        for key, value in (("short_name", "drupal"), ("type", "project_core"), ("project_status", "published")):
            ET.SubElement(project, key).text = value
        releases = ET.SubElement(project, "releases")
        for version in versions:
            release = ET.SubElement(releases, "release")
            ET.SubElement(release, "version").text = version
            ET.SubElement(release, "status").text = "published"
        ET.ElementTree(project).write(self.root / "feed.xml", encoding="utf-8", xml_declaration=True)
        return project

    def archive(self, version, missing=None, directory_version=None):
        with tarfile.open(self.root / f"drupal-{version}.tar.gz", "w:gz") as archive:
            for marker in MARKERS:
                if marker == missing:
                    continue
                data = b"Drupal fixture\n"
                member = tarfile.TarInfo(f"drupal-{directory_version or version}/{marker}")
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

    def values(self):
        return {"steps.version.outputs.version": BASELINE,
                "steps.install.outputs.baseline_version": BASELINE,
                **{f"steps.test{i}.{key}": value for i in range(1, 7)
                   for key, value in (("outputs.status", "passed"), ("outputs.duration", "1"), ("outcome", "success"))}}

    def run_step(self, name, values=None, **environment):
        values = self.values() if values is None else values

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

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[name]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["/bin/bash", "-euo", "pipefail", "-c", script], cwd=self.root,
                                env={**self.env, **environment}, capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def assert_failed(self, result, outputs, decision):
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", outputs["status"])
        self.assertEqual(decision, outputs["decision"])
        self.assertRegex(outputs["duration"], r"^[0-9]+$")
        self.assertNotEqual(CANDIDATE, outputs["next_installed_version"])
        values = self.values()
        values.update({"steps.test6.outputs.status": outputs["status"], "steps.test6.outcome": "failure"})
        summary, counts = self.run_step("summary", values)
        self.assertNotEqual(0, summary.returncode)
        self.assertEqual(("5", "1", "0", "failure"),
                         tuple(counts[key] for key in ("passed", "failed", "core_failed", "overall_status")))

    def requests(self):
        path = self.root / "requests"
        return [json.loads(line)[-1] for line in path.read_text().splitlines()] if path.exists() else []

    def test_real_workflow_selects_stable_and_checks_actual_extracted_archive_without_rg(self):
        self.assertFalse((self.bin / "rg").exists())
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(("passed", "next_install_validated", CANDIDATE, CANDIDATE),
                         tuple(outputs[key] for key in ("status", "decision", "latest_version", "next_installed_version")))
        self.assertEqual(["https://updates.drupal.org/release-history/drupal/current",
                          f"https://ftp.drupal.org/files/projects/drupal-{CANDIDATE}.tar.gz"], self.requests())
        self.assertEqual(4, len([path for path in self.root.glob(f"tmp.*/drupal-{CANDIDATE}/**/*") if path.is_file()]))
        summary, counts = self.run_step("summary")
        self.assertEqual(0, summary.returncode, summary.stderr)
        self.assertEqual(("6", "0", "success"), tuple(counts[key] for key in ("passed", "failed", "overall_status")))

    def test_numeric_version_order_does_not_depend_on_feed_order_or_prerelease_prefix(self):
        self.feed(["11.9.9", "12.0.0-rc1", "11.10.0", "11.10.0-beta1", "11.2.5"])
        self.archive("11.10.0")
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("11.10.0", outputs["latest_version"])

    def test_network_http_and_producer_failures_never_use_valid_partial_output(self):
        for code in (6, 22, 23, 28):
            with self.subTest(code=code):
                result, outputs = self.run_step("test6", LOOKUP_EXIT=str(code))
                self.assert_failed(result, outputs, "next_lookup_failed")
                self.assertNotIn("latest_version", outputs)
                self.assertTrue(all("release-history" in url for url in self.requests()))

    def test_missing_required_tools_fail_without_fallback(self):
        for tool, decision in (("curl", "next_lookup_failed"), ("python3", "next_lookup_failed"),
                               ("tar", "next_install_failed")):
            with self.subTest(tool=tool):
                path = self.bin / tool
                backup = self.bin / f"{tool}.disabled"
                path.rename(backup)
                before = len(self.requests())
                try:
                    self.assert_failed(*self.run_step("test6"), decision)
                    self.assertEqual(before + (tool == "tar"), len(self.requests()))
                finally:
                    backup.rename(path)
        self.assertTrue(all("release-history" in url for url in self.requests()))

    def test_malformed_xml_schema_identity_status_and_versions_fail_closed(self):
        valid = (self.root / "feed.xml").read_text()
        cases = ["", "<project>", "<html>11.4.6</html>",
                 valid.replace("<short_name>drupal", "<short_name>another"),
                 valid.replace("project_core", "project_module"),
                 valid.replace("<project_status>published", "<project_status>unpublished"),
                 valid.replace("<status>published", "<status>unpublished"),
                 valid.replace(f"<version>{CANDIDATE}</version>", ""),
                 valid.replace(f"<version>{CANDIDATE}", "<version>11.04.6"),
                 valid.replace(f"<version>{CANDIDATE}", "<version>11.4.bad"),
                 valid.replace(f"<version>{CANDIDATE}", "<version>11.4.6;touch unexpected")]
        for source in cases:
            with self.subTest(source=source):
                (self.root / "feed.xml").write_text(source)
                self.assert_failed(*self.run_step("test6"), "next_lookup_failed")
        self.assertTrue(all("release-history" in url for url in self.requests()))

    def test_empty_unstable_only_and_non_newer_feeds_fail_instead_of_skipping(self):
        for versions in ([], ["12.0.0-alpha1", "12.0.x-dev", "dev-main"], [BASELINE], ["10.2.3"]):
            with self.subTest(versions=versions):
                self.feed(versions)
                self.assert_failed(*self.run_step("test6"), "next_lookup_failed")
        self.assertTrue(all("release-history" in url for url in self.requests()))

    def test_unknown_or_malformed_baseline_fails_selection(self):
        for baseline in ("unknown", "", "10.2", "v10.2.4", "10.2.4-beta1"):
            with self.subTest(baseline=baseline):
                values = self.values()
                values["steps.version.outputs.version"] = baseline
                self.assert_failed(*self.run_step("test6", values), "next_lookup_failed")

    def test_candidate_download_and_real_tar_extraction_failures_are_not_lookup_success(self):
        for environment in ({"ARCHIVE_EXIT": "22"}, {"ARCHIVE_EXIT": "28"}, {"CORRUPT_ARCHIVE": "1"}):
            with self.subTest(environment=environment):
                result, outputs = self.run_step("test6", **environment)
                self.assert_failed(result, outputs, "next_install_failed")
                self.assertEqual(CANDIDATE, outputs["latest_version"])

    def test_every_existing_candidate_layout_marker_and_exact_directory_remains_required(self):
        for missing in MARKERS:
            with self.subTest(missing=missing):
                self.archive(CANDIDATE, missing=missing)
                self.assert_failed(*self.run_step("test6"), "next_install_failed")
        self.archive(CANDIDATE, directory_version=BASELINE)
        self.assert_failed(*self.run_step("test6"), "next_install_failed")

    def test_baseline_install_and_all_five_existing_source_checks_are_preserved(self):
        result, outputs = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(BASELINE, outputs["baseline_version"])
        for number in range(1, 6):
            result, outputs = self.run_step(f"test{number}")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("passed", outputs["status"])
        result, outputs = self.run_step("test4", TEST_ARCH="x86_64")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def test_summary_requires_successful_test6_outcome_and_never_hides_skips(self):
        for status, outcome in (("passed", "failure"), ("passed", "cancelled"), ("passed", ""),
                                ("skipped", "success"), ("failed", "success"), ("", "success")):
            with self.subTest(status=status, outcome=outcome):
                values = self.values()
                values.update({"steps.test6.outputs.status": status, "steps.test6.outcome": outcome})
                result, outputs = self.run_step("summary", values)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failure", outputs["overall_status"])
                self.assertEqual("1", outputs["failed"])

    def test_discovery_declares_tools_and_has_no_html_scraper_or_pinned_fallback(self):
        self.assertIn('--packages "curl python3"', self.steps["install"]["run"])
        self.assertIn('BASELINE_VERSION="10.2.4"', self.steps["install"]["run"])
        for forbidden in ("rg -o", "|| true", 'LATEST_VERSION="11.2.5"', "status=skipped", "metadata_review_required"):
            self.assertNotIn(forbidden, self.steps["test6"]["run"])


if __name__ == "__main__":
    unittest.main()
