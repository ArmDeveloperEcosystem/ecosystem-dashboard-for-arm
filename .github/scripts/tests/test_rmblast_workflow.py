"""Offline RMBlast workflow fault tests, not native Arm build/runtime evidence."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-rmblast.yml"
RECIPE_REVISION = "2016cbf067d3febb0167d31011723bdf5e47aacd"
NEXT_RECIPE_REVISION = "b2671b6b68ddf3b2117d0cb4ffa09f9f038142d2"


class RMBlastWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rmblast-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-rmblast"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ | self.job["env"],
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        RMBLAST_PREFIX=str(self.root / "install"), TMPDIR=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"), GITHUB_PATH=str(self.root / "path"),
                        TRACE=str(self.root / "trace"), PREFIX_FILE=str(self.root / "prefix"),
                        FIXTURE_ROOT=str(self.root))
        self.values = {f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)}
        self.script(".github/actions/apt-bootstrap/bootstrap.sh", "exit 0\n")
        self.script("bin/sleep", "exit 0\n")
        self.script("bin/timeout", 'while [[ "$1" == --* ]]; do shift; done\nshift\nexec "$@"\n')
        self.script("bin/file", 'printf "%s\\n" "${BINARY_ARCH:-ELF 64-bit ARM aarch64}"\n')
        self.script("bin/make", '''
printf 'make %s\n' "$*" >> "$TRACE"
[ "${MAKE_RC:-0}" = 0 ] || exit "$MAKE_RC"
if [ "$1" = install ]; then
  prefix=$(cat "$PREFIX_FILE")
  mkdir -p "$prefix/bin"
  cp "$FIXTURE_ROOT/rmblastn" "$prefix/bin/rmblastn"
  cp "$FIXTURE_ROOT/makeblastdb" "$prefix/bin/makeblastdb"
fi
''')
        self.script("rmblastn", '''
printf 'rmblastn %s\n' "$*" >> "$TRACE"
[ "${RUNTIME_RC:-0}" = 0 ] || exit "$RUNTIME_RC"
case "$1" in
  -version) printf 'rmblastn: %s+\n' "${INSTALLED_VERSION:-$BUILD_VERSION}" ;;
  -help) printf 'RMBlast help\n' ;;
  *) printf 'query1\tdb1\t28\n' ;;
esac
''')
        self.script("makeblastdb", '''
printf 'makeblastdb %s\n' "$*" >> "$TRACE"
exit "${RUNTIME_RC:-0}"
''')
        self.python_script("bin/curl", '''
import json, os, pathlib, sys
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith("https://"))
source = "SOURCE" if "ftp.ncbi.nlm.nih.gov" in url else "PATCH"
mode = os.environ.get(source + "_MODE", "ok")
if "--head" in args:
    sys.exit(22 if mode == "error" else 0)
output = pathlib.Path(args[args.index("-o") + 1])
with open(os.environ["TRACE"], "a") as trace:
    trace.write(json.dumps({"url": url, "bytes_before": output.stat().st_size if output.exists() else 0}) + "\\n")
if mode == "error":
    sys.exit(22)
payload = pathlib.Path(os.environ[source + "_FIXTURE"]).read_bytes()
if mode == "maintenance":
    payload = b"site down for maintenance"
elif mode == "truncated":
    payload = payload[:len(payload) // 2]
elif mode == "partial":
    output.write_bytes(payload[:10])
    sys.exit(18)
output.write_bytes(payload)
''')
        self.python_script("bin/sha256sum", '''
import hashlib, pathlib, sys
assert sys.argv[1:] == ["-c", "-"]
for line in sys.stdin:
    expected, filename = line.strip().split(maxsplit=1)
    if hashlib.sha256(pathlib.Path(filename).read_bytes()).hexdigest() != expected:
        raise SystemExit(1)
''')
        self.script("bin/python3", f'exec "{sys.executable}" "$@"\n')

    def script(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\nset -eu\n" + body)
        path.chmod(0o755)

    def python_script(self, name, body):
        path = self.root / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    def bundle(self, version="2.14.1", candidate=False):
        if candidate:
            version = "2.17.0"
        archive = self.root / "source.tgz"
        configure = '''#!/bin/bash
set -eu
grep -q '^patched$' fixture.txt
printf 'configure\n' >> "$TRACE"
for arg in "$@"; do
  case "$arg" in --prefix=*) printf '%s\n' "${arg#--prefix=}" > "$PREFIX_FILE" ;; esac
done
'''
        with tarfile.open(archive, "w:gz") as output:
            for name, content in {"configure": configure, "fixture.txt": "original\n"}.items():
                member = tarfile.TarInfo(f"ncbi-blast-{version}+-src/c++/{name}")
                data = content.encode()
                member.mode = 0o755 if name == "configure" else 0o644
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))
        delta = b"--- a/c++/fixture.txt\n+++ b/c++/fixture.txt\n@@ -1 +1 @@\n-original\n+patched\n"
        patch_file = self.root / "patch"
        patch_file.write_bytes(delta)
        prefix = "RMBLAST_NEXT" if candidate else "RMBLAST"
        return {"SOURCE_FIXTURE": str(archive), "PATCH_FIXTURE": str(patch_file),
                prefix + "_SOURCE_SHA256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                prefix + "_PATCH_SHA256": hashlib.sha256(patch_file.read_bytes()).hexdigest(),
                "BUILD_VERSION": "2.17.1" if candidate else version}

    def render(self, text):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                conditional = re.fullmatch(r"\(([\w.]+) == '([^']+)' && '([^']+)'\)", term)
                if conditional:
                    value = conditional[3] if self.values.get(conditional[1]) == conditional[2] else ""
                elif term.startswith("'"):
                    value = term[1:-1]
                else:
                    value = self.values.get(term, term if term.isdigit() else "")
                if value:
                    return value
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, text)

    def run_step(self, step, **environment):
        script = self.render(self.steps[step]["run"])
        script = script.replace("/tmp/rmblast-", str(self.root / "rmblast-"))
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        Path(self.env["TRACE"]).write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **environment),
                                text=True, capture_output=True, timeout=15)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def downloads(self):
        return [json.loads(line) for line in Path(self.env["TRACE"]).read_text().splitlines()
                if line.startswith("{")]

    def assert_no_build(self):
        self.assertNotIn("configure\n", Path(self.env["TRACE"]).read_text())
        self.assertNotIn("make ", Path(self.env["TRACE"]).read_text())

    def test_baseline_provenance_and_all_six_checks_remain(self):
        self.assertEqual("2.14.1", self.job["env"]["RMBLAST_VERSION"])
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual("https://raw.githubusercontent.com/bioconda/bioconda-recipes/"
                         + RECIPE_REVISION + "/recipes/rmblast/isb-2.14.1+-rmblast.patch",
                         self.job["env"]["RMBLAST_PATCH_URL"])
        self.assertEqual("fe72f36f21e6d3a72f80ed39e993fe2bb94a94f03cdb194610aa829b51664fba",
                         self.job["env"]["RMBLAST_PATCH_SHA256"])
        self.assertEqual("712c2dbdf0fb13cc1c2d4f4ef5dd1ce4b06c3b57e96dfea8f23e6e99f5b1650e",
                         self.job["env"]["RMBLAST_SOURCE_SHA256"])
        self.assertEqual("2.17.1", self.job["env"]["RMBLAST_NEXT_VERSION"])
        self.assertEqual("2.17.0", self.job["env"]["RMBLAST_NEXT_SOURCE_VERSION"])
        self.assertEqual("https://raw.githubusercontent.com/bioconda/bioconda-recipes/"
                         + NEXT_RECIPE_REVISION + "/recipes/rmblast/isb-2.17.1+-rmblast.patch",
                         self.job["env"]["RMBLAST_NEXT_PATCH_URL"])
        self.assertEqual("585d8da648e9a19a0ef069aacb68229522304c6a82d02a7e7486cfb16a84d73d",
                         self.job["env"]["RMBLAST_NEXT_PATCH_SHA256"])
        self.assertEqual("502057a88e9990e34e62758be21ea474cc0ad68d6a63a2e37b2372af1e5ea147",
                         self.job["env"]["RMBLAST_NEXT_SOURCE_SHA256"])
        self.assertEqual([f"test{i}" for i in range(1, 7)],
                         [step for step in self.steps if re.fullmatch(r"test\d", step)])
        fixture = self.bundle()
        for step in ("install", "version", "test1", "test2", "test3", "test4", "test5"):
            result, output = self.run_step(step, **fixture)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            if step.startswith("test"):
                self.assertEqual("passed", output["status"])
        trace = Path(self.env["TRACE"]).read_text()
        self.assertIn("makeblastdb -in", trace)
        self.assertIn("rmblastn -query", trace)

    def test_baseline_http_maintenance_truncation_and_checksum_fail_closed(self):
        for source in ("SOURCE", "PATCH"):
            for mode in ("error", "maintenance", "truncated", "partial"):
                with self.subTest(source=source, mode=mode):
                    result, output = self.run_step("install", **self.bundle(), **{source + "_MODE": mode})
                    self.assertNotEqual(0, result.returncode)
                    self.assertNotIn("install_status", output)
                    self.assert_no_build()
                    calls = self.downloads()
                    failed_calls = [call for call in calls
                                    if ("ftp.ncbi.nlm.nih.gov" in call["url"]) == (source == "SOURCE")]
                    self.assertEqual(3, len(failed_calls))
                    self.assertTrue(all(call["bytes_before"] == 0 for call in calls))
        for digest in ("RMBLAST_SOURCE_SHA256", "RMBLAST_PATCH_SHA256"):
            result, _ = self.run_step("install", **(self.bundle() | {digest: "0" * 64}))
            self.assertNotEqual(0, result.returncode)
            self.assert_no_build()

    def test_candidate_invalid_pins_fail_instead_of_skipping(self):
        for variable, value in (("RMBLAST_NEXT_VERSION", ""), ("RMBLAST_NEXT_VERSION", "2.17.1-rc1"),
                                ("RMBLAST_NEXT_VERSION", "2.14.1"), ("RMBLAST_NEXT_VERSION", "2.13.0"),
                                ("RMBLAST_NEXT_SOURCE_VERSION", "")):
            with self.subTest(variable=variable, value=value):
                result, output = self.run_step("test6", **self.bundle(candidate=True), **{variable: value})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])
                self.assertEqual("next_lookup_failed", output["decision"])
                self.assertEqual("unknown", output["latest_version"])
                self.assertEqual([], self.downloads())
                self.assert_no_build()

    def test_pinned_candidate_preserves_source_build_and_runtime(self):
        result, output = self.run_step("test6", **self.bundle(candidate=True))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("2.17.1", output["latest_version"])
        self.assertEqual("2.17.1", output["next_installed_version"])
        self.assertEqual("next_install_validated", output["decision"])
        self.assertEqual("passed", output["status"])
        trace = Path(self.env["TRACE"]).read_text()
        for command in ("configure\n", "make -j2", "make install", "makeblastdb -in", "rmblastn -query"):
            self.assertIn(command, trace)
        self.assertEqual(["https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/"
                          "ncbi-blast-2.17.0+-src.tar.gz", self.job["env"]["RMBLAST_NEXT_PATCH_URL"]],
                         [call["url"] for call in self.downloads()])
        self.assertNotIn("urlopen", self.steps["test6"]["run"])
        self.assertNotIn("status=skipped", self.steps["test6"]["run"])
        self.assertIn("explicit pinned candidate", output["comparison"])
        self.assertIn("not the latest release", output["comparison"])

    def test_candidate_bad_downloads_and_gzip_never_reach_build(self):
        for source in ("SOURCE", "PATCH"):
            for mode in ("error", "maintenance", "truncated", "partial"):
                with self.subTest(source=source, mode=mode):
                    result, output = self.run_step("test6", **self.bundle(candidate=True),
                                                   **{source + "_MODE": mode})
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", output["status"])
                    self.assertEqual("next_install_failed", output["decision"])
                    self.assert_no_build()
                    calls = self.downloads()
                    failed_calls = [call for call in calls
                                    if ("ftp.ncbi.nlm.nih.gov" in call["url"]) == (source == "SOURCE")]
                    self.assertEqual(3, len(failed_calls))
                    self.assertTrue(all(call["bytes_before"] == 0 for call in calls))

    def test_candidate_checksum_and_gzip_gates_are_independent(self):
        for digest in ("RMBLAST_NEXT_SOURCE_SHA256", "RMBLAST_NEXT_PATCH_SHA256"):
            result, output = self.run_step("test6", **(self.bundle(candidate=True) | {digest: "0" * 64}))
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("next_install_failed", output["decision"])
            self.assert_no_build()
        fixture = self.bundle(candidate=True)
        archive = Path(fixture["SOURCE_FIXTURE"])
        archive.write_bytes(archive.read_bytes()[:100])
        fixture["RMBLAST_NEXT_SOURCE_SHA256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
        result, output = self.run_step("test6", **fixture)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertEqual("next_install_failed", output["decision"])
        self.assert_no_build()

    def test_candidate_build_version_architecture_and_runtime_failures_cannot_pass(self):
        for environment in ({"MAKE_RC": "1"}, {"INSTALLED_VERSION": "2.14.1"},
                            {"INSTALLED_VERSION": "2.17.10"},
                            {"BINARY_ARCH": "ELF x86-64"}, {"RUNTIME_RC": "1"}):
            with self.subTest(environment=environment):
                result, output = self.run_step("test6", **self.bundle(candidate=True), **environment)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])
                self.assertEqual("next_install_failed", output["decision"])
                self.assertEqual("validation_failed", output["next_installed_version"])
                self.assertTrue(output["duration"].isdigit())
                self.values.update({f"steps.test6.outputs.{key}": value for key, value in output.items()})
                self.assertEqual("next_install_failed", self.render(self.job["outputs"]["regression_decision"]))

    def test_summary_and_outputs_preserve_regression_failures(self):
        self.assertEqual("${{ steps.test6.outputs.decision || 'not_configured' }}",
                         self.job["outputs"]["regression_decision"])
        for explicit in (True, False):
            with self.subTest(explicit=explicit):
                self.values["steps.test6.outcome"] = "failure"
                if explicit:
                    self.values["steps.test6.outputs.status"] = "failed"
                    self.values["steps.test6.outputs.decision"] = "next_lookup_failed"
                else:
                    self.values.pop("steps.test6.outputs.status", None)
                    self.values.pop("steps.test6.outputs.decision", None)
                result, output = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("5", output["passed"])
                self.assertEqual("1", output["failed"])
                self.assertEqual("failure", output["overall_status"])
                self.assertEqual("failing", output["badge_status"])
                self.assertEqual("failed", self.render(self.job["outputs"]["regression_status"]))
                human_summary = next(step["run"] for step in self.job["steps"]
                                     if step["name"] == "Create test summary")
                self.assertIn("6. Regression Validation: failed", self.render(human_summary))
                self.assertEqual("next_lookup_failed" if explicit else "not_configured",
                                 self.render(self.job["outputs"]["regression_decision"]))
        self.values["steps.test6.outputs.status"] = "passed"
        self.values["steps.test6.outcome"] = "success"
        result, output = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", output["passed"])
        self.assertEqual("success", output["overall_status"])


if __name__ == "__main__":
    unittest.main()
