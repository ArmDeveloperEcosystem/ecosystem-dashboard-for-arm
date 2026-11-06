"""Exercise official downloads and fail-closed TurboVNC runtime/artifact checks."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-turbovnc.yml"


class TurboVNCWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="turbovnc-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "next-src").mkdir()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-turbovnc"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.env = dict(os.environ, **self.job["env"],
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        GITHUB_OUTPUT=str(self.root / "output"), TMPDIR=str(self.root),
                        TRACE=str(self.root / "trace"))
        self.stub("curl", '''
args = sys.argv[1:]
assert args == ["-fL", "--retry", "3", "-o", args[4], os.environ["EXPECTED_URL"]], args
if os.environ.get("DOWNLOAD_RC"):
    sys.exit(int(os.environ["DOWNLOAD_RC"]))
Path(args[4]).write_text("package fixture")
''')
        self.stub("dpkg-deb", '''
args = sys.argv[1:]
assert Path(args[1]).is_file()
if args[0] == "-f":
    fields = {"Package": os.environ.get("PACKAGE", "turbovnc"),
              "Architecture": os.environ.get("ARCH", "arm64"),
              "Version": os.environ.get("PACKAGE_VERSION", os.environ["VERSION"] + "-20220503")}
    print("\\n".join(fields[field] for field in args[2:]))
elif args[0] == "-x":
    if os.environ.get("MISSING_XVNC") != "1":
        binary = Path(args[2]) / "opt/TurboVNC/bin/Xvnc"
        binary.parent.mkdir(parents=True)
        binary.write_text("ELF fixture")
else:
    sys.exit(1)
''')
        self.stub("file", 'print(os.environ.get("FILE_OUTPUT", "ELF 64-bit LSB executable, ARM aarch64"))\n')
        self.stub("sudo", '''
assert sys.argv[1:5] == ["apt-get", "install", "-y", "--no-install-recommends"]
assert Path(sys.argv[5]).is_file()
sys.exit(int(os.environ.get("INSTALL_RC", "0")))
''')
        self.stub("dpkg-query", 'print(os.environ.get("INSTALLED_VERSION", os.environ["VERSION"] + "-20220503"))\n')
        self.stub("Xvnc", '''
import signal
if sys.argv[1:] == ["-version"]:
    print("TurboVNC Server (Xvnc) 64-bit v" + os.environ.get("BANNER_VERSION", os.environ["VERSION"]) + " (fixture)")
    sys.exit(int(os.environ.get("VERSION_RC", "0")))
assert sys.argv[1:] == ["-displayfd", "3", "-geometry", "800x600", "-depth", "24",
                        "-SecurityTypes", "None", "-rfbport", "0", "-localhost", "-nolisten", "tcp"]
if os.environ.get("START_RC"):
    sys.exit(int(os.environ["START_RC"]))
def stop(*args):
    with open(os.environ["TRACE"], "a") as stream:
        stream.write(json.dumps(["Xvnc-stopped"]) + "\\n")
    sys.exit(int(os.environ.get("STOP_RC", "0")))
signal.signal(signal.SIGTERM, stop)
os.write(3, (os.environ.get("DISPLAY_NUM", "17") + "\\n").encode())
while True:
    signal.pause()
''')
        self.stub("xdpyinfo", '''
assert sys.argv[1:] == ["-display", ":17"]
print("dimensions:    " + os.environ.get("GEOMETRY", "800x600") + " pixels")
sys.exit(int(os.environ.get("DISPLAY_RC", "0")))
''')
        self.stub("sleep", 'import time\ntime.sleep(0.01)\n')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + '''
import json, os, sys
from pathlib import Path
with open(os.environ["TRACE"], "a") as stream:
    stream.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + "\\n")
''' + body)
        path.chmod(0o755)

    def run_probe(self, candidate=False, tag=None, **env):
        version = "3.3.1" if candidate else "3.0"
        tag = version if tag is None else tag
        script = (self.steps["test6"]["with"]["limited_cpu_probe"] if candidate
                  else self.steps["test5"]["run"])
        script = re.sub(r"\$\{\{.*?\}\}", lambda match: tag, script)
        script = script.replace("/opt/TurboVNC/bin/Xvnc", str(self.bin / "Xvnc"))
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        trace = Path(self.env["TRACE"])
        trace.write_text("")
        url = f"https://github.com/TurboVNC/turbovnc/releases/download/{tag}/turbovnc_{version}_arm64.deb"
        result = subprocess.run(["bash", "-euo", "pipefail", "-c", script], cwd=self.root,
                                env=dict(self.env, VERSION=version, LATEST_VERSION=version,
                                         CANDIDATE_TAG=tag, EXPECTED_URL=url, **env),
                                capture_output=True, text=True, timeout=20)
        fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
        calls = [json.loads(line) for line in trace.read_text().splitlines()]
        return result, fields, calls

    def test_downloads_official_versioned_arm64_packages_without_api_lookup(self):
        for candidate in (False, True):
            with self.subTest(candidate=candidate):
                result, fields, calls = self.run_probe(candidate)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                downloads = [call for call in calls if call[0] == "curl"]
                self.assertEqual(1, len(downloads))
                self.assertIn("Downloading " + downloads[0][-1], result.stdout)
                if candidate:
                    self.assertFalse(any(call[0] in ("sudo", "dpkg-query", "Xvnc", "xdpyinfo") for call in calls))
                else:
                    self.assertEqual("passed", fields["status"])
                    self.assertIn(["xdpyinfo", "-display", ":17"], calls)
                    self.assertIn(["Xvnc-stopped"], calls)
                    self.assertIn("WAN client performance, VirtualGL, and 3D remoting were not claimed", fields["note"])

    def test_download_and_package_proof_failures_are_fatal_for_both_versions(self):
        failures = ({"DOWNLOAD_RC": "22"}, {"ARCH": "amd64"}, {"PACKAGE": "other"},
                    {"PACKAGE_VERSION": "9.0-1"}, {"MISSING_XVNC": "1"},
                    {"FILE_OUTPUT": "ELF 64-bit LSB executable, x86-64"})
        for candidate in (False, True):
            for env in failures:
                with self.subTest(candidate=candidate, env=env):
                    result, fields, calls = self.run_probe(candidate, **env)
                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertNotEqual("passed", fields.get("status"))
                    self.assertFalse(any(call[0] == "sudo" for call in calls))

    def test_tag_must_match_the_version_before_downloading(self):
        for candidate in (False, True):
            for tag in ("", "default_branch", "external_artifact", "3.1"):
                with self.subTest(candidate=candidate, tag=tag):
                    result, fields, calls = self.run_probe(candidate, tag=tag)
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse(any(call[0] == "curl" for call in calls))
                    self.assertNotEqual("passed", fields.get("status"))

    def test_baseline_install_version_display_and_shutdown_failures_still_fail(self):
        failures = ({"INSTALL_RC": "1"}, {"INSTALLED_VERSION": "3.1-1"},
                    {"VERSION_RC": "1"}, {"BANNER_VERSION": "3.1"}, {"START_RC": "1"},
                    {"DISPLAY_NUM": "invalid"}, {"DISPLAY_RC": "1"},
                    {"GEOMETRY": "640x480"}, {"STOP_RC": "1"})
        for env in failures:
            with self.subTest(env=env):
                result, fields, _ = self.run_probe(**env)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("failed", fields["status"])

    def test_scope_and_failure_reporting_remain_explicit(self):
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual("3.0", self.job["env"]["BASELINE_VERSION"])
        self.assertEqual("not_installed", self.job["outputs"]["regression_next_installed_version"])
        regression = self.steps["test6"]["with"]
        self.assertNotIn("defer_on_limited_cpu_probe_failure", regression)
        self.assertIn("It does not prove WAN client performance, VirtualGL, or 3D remoting", regression["limited_cpu_description"])
        self.assertIn('test "$FAILED" -eq 0', self.steps["summary"]["run"])


if __name__ == "__main__":
    unittest.main()
