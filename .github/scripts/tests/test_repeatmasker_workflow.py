"""Offline fault tests of RepeatMasker workflow shell, not Arm runtime evidence."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-repeatmasker.yml"


class RepeatMaskerWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="repeatmasker-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-repeatmasker"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.base = self.root / "smoke/baseline/RepeatMasker"
        self.env = dict(os.environ | self.job["env"],
                        REPEATMASKER_WORKDIR=str(self.root / "smoke"),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        GITHUB_OUTPUT=str(self.root / "output"),
                        DOWNLOAD_TRACE=str(self.root / "download-trace"))
        self.values = {"steps.install.outputs.base_dir": str(self.base),
                       "steps.version.outputs.version": "4.1.0",
                       "steps.version.outputs.latest": "4.2.5"}
        for number in range(1, 7):
            self.values[f"steps.test{number}.outputs.status"] = "passed"
        self.script(".github/actions/apt-bootstrap/bootstrap.sh", "exit 0\n")
        self.script(".github/scripts/download-with-fallback.sh", '''
printf '%s\n' "$2" > "$DOWNLOAD_TRACE"
[ "${DOWNLOAD_RC:-0}" = 0 ] || exit "$DOWNLOAD_RC"
cp "$FIXTURE" "$1"
''')
        self.script("bin/python3", "printf '4.2.5\\n'\n")
        self.script("bin/uname", 'printf "%s\\n" "${HOST_ARCH:-aarch64}"\n')

    def script(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\nset -eu\n" + body)
        path.chmod(0o755)

    def bundle(self, version="4.1.0", broken=False):
        archive = self.root / "fixture.tar.gz"
        source = (f'print "RepeatMasker version {version}\\n";\n'
                  'exit int($ENV{"PERL_RC"} || 0);\n')
        if broken:
            source = "this is not valid perl {\n"
        with tarfile.open(archive, "w:gz") as output:
            for name, data in {"RepeatMasker": source, "ProcessRepeats": "1;\n",
                               "Libraries/README": "fixture\n"}.items():
                member = tarfile.TarInfo("RepeatMasker-upstream/" + name)
                payload = data.encode()
                member.size = len(payload)
                output.addfile(member, io.BytesIO(payload))
        return {"FIXTURE": str(archive),
                "REPEATMASKER_SHA256": hashlib.sha256(archive.read_bytes()).hexdigest()}

    def run_step(self, step, **environment):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else self.values.get(term, "")
                if value or term.isdigit():
                    return str(value or term)
            return ""
        script = self.steps[step]["run"].replace("/tmp/repeatmasker-", str(self.root / "repeatmasker-"))
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **environment),
                                capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def test_baseline_uses_pinned_official_release_source_and_normalizes_archive_root(self):
        self.assertEqual("4.1.0", self.job["env"]["REPEATMASKER_VERSION"])
        self.assertEqual("ee4929ebdb832bfadca66a6708dbd1d65792e6ca", self.job["env"]["REPEATMASKER_REVISION"])
        result, output = self.run_step("install", **self.bundle())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("success", output["install_status"])
        self.assertTrue((self.base / "RepeatMasker").is_file())
        self.assertEqual("https://codeload.github.com/Dfam-consortium/RepeatMasker/tar.gz/"
                         + self.job["env"]["REPEATMASKER_REVISION"],
                         (self.root / "download-trace").read_text().strip())

    def test_failed_download_and_corrupt_archive_cannot_install(self):
        for override in ({"DOWNLOAD_RC": "22"}, {"REPEATMASKER_SHA256": "0" * 64}):
            with self.subTest(override=override):
                result, output = self.run_step("install", **(self.bundle() | override))
                self.assertNotEqual(0, result.returncode)
                self.assertNotEqual("success", output.get("install_status"))

    def test_core_shell_retains_all_checks_and_rejects_runtime_failures(self):
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        result, _ = self.run_step("install", **self.bundle())
        self.assertEqual(0, result.returncode, result.stderr)
        for step in ("version", "test1", "test2", "test3", "test4", "test5"):
            result, output = self.run_step(step)
            self.assertEqual(0, result.returncode, result.stderr)
            if step != "version":
                self.assertEqual("passed", output["status"])
        for step in ("version", "test2", "test3", "test5"):
            result, output = self.run_step(step, PERL_RC="1")
            self.assertNotEqual(0, result.returncode)
            self.assertNotEqual("passed", output.get("status"))
        result, output = self.run_step("test4", HOST_ARCH="x86_64")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])

    def test_wrong_baseline_version_is_not_replaced_by_the_pin(self):
        self.run_step("install", **self.bundle("4.1.0-alpha-1"))
        result, output = self.run_step("version")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("version", output)

    def test_candidate_runs_checks_and_requires_exact_version(self):
        for version, broken, passed in [("4.2.5", False, True), ("4.2.50", False, False),
                                        ("4.2.5-alpha-1", False, False), ("4.2.5", True, False)]:
            with self.subTest(version=version, broken=broken):
                result, output = self.run_step("test6", **self.bundle(version, broken))
                self.assertEqual(passed, result.returncode == 0, result.stderr)
                self.assertEqual(passed, output.get("status") == "passed")
                if passed:
                    self.assertEqual("4.2.5", output["next_installed_version"])
        self.assertEqual("https://codeload.github.com/Dfam-consortium/RepeatMasker/tar.gz/refs/tags/v4.2.5",
                         (self.root / "download-trace").read_text().strip())

    def test_candidate_download_failure_and_same_release_fail(self):
        result, output = self.run_step("test6", **self.bundle("4.2.5"), DOWNLOAD_RC="22")
        self.assertNotEqual(0, result.returncode)
        self.assertNotEqual("passed", output.get("status"))
        self.values["steps.version.outputs.latest"] = "4.1.0"
        result, output = self.run_step("test6", **self.bundle())
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("next_install_failed", output["decision"])

    def test_release_discovery_parses_official_stable_metadata_and_fails_closed(self):
        code = self.steps["version"]["run"].split("python3 - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
        stable = {"tag_name": "v4.2.5", "draft": False, "prerelease": False}
        for change in ({}, {"draft": True}, {"prerelease": True},
                       {"tag_name": "v4.2.5-rc1"}, {"tag_name": "../../other"}):
            response = io.StringIO(json.dumps(stable | change))
            output = io.StringIO()
            with patch.dict(os.environ, {"GH_TOKEN": "unit-test-token"}), \
                 patch("urllib.request.urlopen", return_value=response) as fetch, \
                 contextlib.redirect_stdout(output):
                if change:
                    with self.assertRaises(SystemExit):
                        exec(compile(code, str(WORKFLOW), "exec"), {})
                else:
                    exec(compile(code, str(WORKFLOW), "exec"), {})
                    self.assertEqual("4.2.5\n", output.getvalue())
                self.assertEqual("https://api.github.com/repos/Dfam-consortium/RepeatMasker/releases/latest",
                                 fetch.call_args.args[0].full_url)
        with patch.dict(os.environ, {"GH_TOKEN": "unit-test-token"}), \
             patch("urllib.request.urlopen", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                exec(compile(code, str(WORKFLOW), "exec"), {})

    def test_summary_never_reports_success_for_failed_or_missing_regression(self):
        for status in ("failed", ""):
            self.values["steps.test6.outputs.status"] = status
            result, output = self.run_step("summary")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failure", output["overall_status"])
            self.assertEqual("1", output["failed"])


if __name__ == "__main__":
    unittest.main()
