"""Offline NetBSD download fault tests; simulated QEMU is not Arm boot evidence."""

import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


GITHUB = Path(__file__).resolve().parents[2]
WORKFLOW = GITHUB / "workflows/test-netbsd.yml"
ARCHIVE = "https://archive.netbsd.org/pub/NetBSD-archive"
CDN = "https://cdn.netbsd.org/pub/NetBSD"
IMAGE_PATH = "evbarm-aarch64/binary/gzimg/arm64.img.gz"


class NetBSDWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="netbsd-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-netbsd"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.fixture = self.root / "fixture.img.gz"
        self.fixture.write_bytes(gzip.compress(b"unit fixture, not a bootable NetBSD image\n"))
        self.env = dict(os.environ | self.job["env"],
                        NETBSD_WORKROOT=str(self.root / "work"),
                        GITHUB_WORKSPACE=str(self.root), GITHUB_OUTPUT=str(self.root / "output"),
                        TRACE=str(self.root / "trace"), FIXTURE=str(self.fixture),
                        TMPDIR=str(self.root), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)}
        self.values.update({"steps.metadata.outputs.regression_policy": "applicable",
                            "steps.version.outputs.version": "10.0",
                            "steps.version.outputs.latest": "10.1",
                            "steps.install.outputs.baseline_dir": str(self.root / "work/baseline")})
        helper = self.root / ".github/scripts/download-with-fallback.sh"
        helper.parent.mkdir(parents=True)
        self.script(".github/actions/apt-bootstrap/bootstrap.sh", "exit 0\n")
        self.script("bin/sleep", "exit 0\n")
        self.script("bin/timeout", 'shift\nexec "$@"\n')
        self.script("bin/qemu-system-aarch64", '''
printf 'qemu\n' >> "$TRACE"
printf 'NetBSD %s (GENERIC64)\n' "${BOOT_VERSION:-10.1}"
if [ "${ROOT_MOUNTED:-yes}" = yes ]; then
  printf 'root on dk1\n'
fi
exit 124
''')
        client = self.root / "download.py"
        client.write_text('''
import json, os, pathlib, sys
args = sys.argv[1:]
assert len(args) == 2, "Each helper call must use exactly one URL"
output = pathlib.Path(args[0])
url = args[-1]
size = output.stat().st_size if output.exists() else 0
with open(os.environ["TRACE"], "a") as trace:
    trace.write(json.dumps({"url": url, "bytes_before": size}) + "\\n")
source = "ARCHIVE" if url.startswith("https://archive.netbsd.org/") else "CDN"
mode = os.environ.get(source + "_MODE", "ok")
if mode == "partial":
    with output.open("ab") as stream:
        stream.write(b"truncated download\\n")
    sys.exit(18)
if mode == "error":
    sys.exit(22)
if mode == "corrupt":
    output.write_bytes(b"not gzip\\n")
else:
    # Deliberately append to expose failure to discard another source's partial file.
    with output.open("ab") as stream:
        stream.write(pathlib.Path(os.environ["FIXTURE"]).read_bytes())
''')
        self.script(".github/scripts/download-with-fallback.sh",
                    f'exec "{sys.executable}" "{client}" "$@"\n')

    def script(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\nset -eu\n" + body)
        path.chmod(0o755)

    def run_step(self, step, **environment):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else self.values.get(term, "")
                if value:
                    return value
            return ""

        script = self.steps[step]["run"].replace("/tmp/netbsd-", str(self.root / "netbsd-"))
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        Path(self.env["TRACE"]).write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **environment),
                                capture_output=True, text=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def downloads(self):
        return [json.loads(line) for line in Path(self.env["TRACE"]).read_text().splitlines()
                if line.startswith("{")]

    def assert_no_boot(self):
        self.assertNotIn("qemu", Path(self.env["TRACE"]).read_text().splitlines())

    def test_baseline_and_six_arm_checks_remain_configured(self):
        self.assertEqual("10.0", self.job["env"]["CURRENT_BASELINE_VERSION"])
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual(CDN, self.job["env"]["NETBSD_MIRROR"])
        self.assertEqual(ARCHIVE, self.job["env"]["NETBSD_ARCHIVE_MIRROR"])
        self.assertEqual([f"test{i}" for i in range(1, 7)],
                         [step for step in self.steps if re.fullmatch(r"test\d", step)])
        self.assertIn("candidates[0]", self.steps["version"]["run"])
        for step in ("test5", "test6"):
            self.assertIn("timeout 90 qemu-system-aarch64", self.steps[step]["run"])
            self.assertIn("-cpu cortex-a57", self.steps[step]["run"])
            self.assertIn("root on dk1", self.steps[step]["run"])

    def test_baseline_downloads_exact_official_archive(self):
        result, output = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        url = f"{ARCHIVE}/NetBSD-10.0/{IMAGE_PATH}"
        self.assertEqual(url, output["baseline_url"])
        self.assertEqual("success", output["install_status"])
        self.assertEqual([url], [call["url"] for call in self.downloads()])
        self.assertEqual(self.fixture.read_bytes(),
                         (self.root / "work/baseline/arm64.img.gz").read_bytes())

    def test_baseline_download_error_and_corrupt_gzip_fail(self):
        for mode in ("error", "partial", "corrupt"):
            with self.subTest(mode=mode):
                result, output = self.run_step("install", ARCHIVE_MODE=mode)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("install_status", output)
                self.assert_no_boot()

    def test_candidate_cdn_success_does_not_use_archive(self):
        result, output = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output["status"])
        self.assertEqual("next_install_validated", output["decision"])
        self.assertEqual("10.1", output["next_installed_version"])
        self.assertEqual([f"{CDN}/NetBSD-10.1/{IMAGE_PATH}"],
                         [call["url"] for call in self.downloads()])

    def test_candidate_archive_fallback_discards_partial_download(self):
        for mode in ("error", "partial"):
            with self.subTest(mode=mode):
                result, output = self.run_step("test6", CDN_MODE=mode)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("passed", output["status"])
                calls = self.downloads()
                self.assertEqual([f"{CDN}/NetBSD-10.1/{IMAGE_PATH}"]
                                 + [f"{ARCHIVE}/NetBSD-10.1/{IMAGE_PATH}"],
                                 [call["url"] for call in calls])
                self.assertEqual(0, calls[-1]["bytes_before"])

    def test_candidate_both_sources_fail_without_boot(self):
        result, output = self.run_step("test6", CDN_MODE="partial", ARCHIVE_MODE="error")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertEqual("next_lookup_failed", output["decision"])
        self.assertEqual("not_installed", output["next_installed_version"])
        self.assert_no_boot()

    def test_candidate_corrupt_download_is_not_booted_or_masked_by_fallback(self):
        for environment in ({"CDN_MODE": "corrupt"},
                            {"CDN_MODE": "error", "ARCHIVE_MODE": "corrupt"}):
            with self.subTest(environment=environment):
                result, output = self.run_step("test6", **environment)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])
                self.assertEqual("next_install_failed", output["decision"])
                self.assert_no_boot()
                if environment["CDN_MODE"] == "corrupt":
                    self.assertEqual(1, len(self.downloads()))

    def test_boot_checks_still_require_version_and_root_mount(self):
        for step, version in (("test5", "10.0"), ("test6", "10.1")):
            for environment in ({"BOOT_VERSION": "9.0"},
                                {"BOOT_VERSION": version, "ROOT_MOUNTED": "no"}):
                with self.subTest(step=step, environment=environment):
                    result, output = self.run_step(step, **environment)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", output["status"])

    def test_failed_baseline_prevents_candidate_download(self):
        self.values["steps.test5.outputs.status"] = "failed"
        result, output = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("baseline_failed", output["decision"])
        self.assertEqual("skipped", output["status"])
        self.assertEqual([], self.downloads())
        self.assert_no_boot()


if __name__ == "__main__":
    unittest.main()
