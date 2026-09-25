"""Exercise the actual SDK workflow shells with explicit local command fixtures.

The fake Flatpak/compiler/ELF fixtures test control flow, never native SDK support.
Hosted diagnostic 34439083210 separately proved the real SDK compile/run path.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-freedesktop-sdk.yml"
sys.path.insert(0, str(ROOT / ".github/scripts"))
import package_observation_migration_audit as audit
import package_result_policy as policy

SDK_REF = "runtime/org.freedesktop.Sdk/aarch64/26.08"
PLATFORM_REF = "runtime/org.freedesktop.Platform/aarch64/26.08"
# Captured from the successful hosted diagnostic, not a new remote query.
SDK_COMMIT = "9c59b86fa110cabd49a13f56282202db720e223ddeb90177a5257a421b61ab8d"
PLATFORM_COMMIT = "6bfcf4d4c713168af15870fb9f13b2e43627e0af1af2345f930575ca9fc75099"
VERSION = "26.08.0"
INFO = f"""Freedesktop SDK - Tools and headers for developing applications
          ID: org.freedesktop.Sdk
         Ref: {SDK_REF}
        Arch: aarch64
      Branch: 26.08
     Version: freedesktop-sdk-{VERSION}
      Origin: flathub
      Commit: {SDK_COMMIT}
"""
METADATA = """[Runtime]
name=org.freedesktop.Sdk
runtime=org.freedesktop.Platform/aarch64/26.08
sdk=org.freedesktop.Sdk/aarch64/26.08
"""
OS_RELEASE = 'NAME="Freedesktop SDK"\nID=org.freedesktop.platform\nVERSION_ID=26.08\n'
RUN_OUTPUT = "SDK_RESULT=42\nPTR_BITS=64\n"


class FreedesktopSdkWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-freedesktop-sdk"]
        cls.steps = {step["id"]: step for step in cls.job["steps"] if "id" in step}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sdk workflow ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for command in ("date", "cat", "mkdir", "file", "sha256sum", "rm"):
            real = shutil.which(command)
            self.assertIsNotNone(real, command)
            (self.bin / command).symlink_to(real)
        (self.bin / "python3").symlink_to(sys.executable)
        self.runner = self.root / "runner"
        self.runner.mkdir()
        self.scope = self.runner / "freedesktop-sdk-123-1"
        self.app = self.scope / "application"
        self.app.joinpath("files/bin").mkdir(parents=True)
        self.app.joinpath("metadata").write_text(METADATA.replace("[Runtime]", "[Application]").replace(
            "name=org.freedesktop.Sdk", "name=org.arm.EcosystemSdkSmoke"))
        (self.scope / "owner").write_text("123:1\n")
        self.env = {
            "PATH": str(self.bin), "HOME": str(self.root), "LC_ALL": "C",
            "PYTHONDONTWRITEBYTECODE": "1", "RUNNER_TEMP": str(self.runner),
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(self.root / "step output"), "GITHUB_ENV": str(self.root / "step env"),
            "SDK_SCOPE": str(self.scope), "SDK_APP": str(self.app), "SDK_BRANCH": "26.08",
            "SDK_REF": SDK_REF, "PLATFORM_REF": PLATFORM_REF,
            "SDK_COMMIT": SDK_COMMIT, "PLATFORM_COMMIT": PLATFORM_COMMIT,
            "FLATPAK_USER_DIR": str(self.scope / "flatpak"),
            "XDG_DATA_HOME": str(self.scope / "data"), "XDG_CACHE_HOME": str(self.scope / "cache"),
            "XDG_CONFIG_HOME": str(self.scope / "config"),
            "FLATPAK_FANCY_OUTPUT": "0", "FLATPAK_TTY_PROGRESS": "0",
            "FIXTURE_BIN": str(self.bin), "CALLS": str(self.root / "calls.jsonl"),
            "ARCH": "aarch64", "APT_RC": "0", "INSTALL_RC": "0", "QUERY_RC": "0", "INFO_RC": "0",
            "REMOTE_SDK": SDK_COMMIT, "REMOTE_PLATFORM": PLATFORM_COMMIT,
            "INSTALLED_SDK": SDK_COMMIT, "INSTALLED_PLATFORM": PLATFORM_COMMIT,
            "INSTALLED_SDK_REF": SDK_REF, "INSTALLED_PLATFORM_REF": PLATFORM_REF,
            "ORIGIN": "flathub", "SDK_INFO": INFO, "SDK_METADATA": METADATA,
            "APP_METADATA": self.app.joinpath("metadata").read_text(),
            "OS_RELEASE": OS_RELEASE, "TARGET": "aarch64-unknown-linux-gnu",
            "GCC_RC": "0", "BUILD_RC": "0", "BUILD_INIT_RC": "0", "WRITE_ELF": "1",
            "RUN_RC": "0", "NEGATIVE_RC": "9", "RUN_OUTPUT": RUN_OUTPUT,
        }
        self.values = {
            "steps.install.outcome": "success", "steps.install.outputs.install_status": "success",
            "steps.install.outputs.installation_method": "flatpak",
            "steps.version.outcome": "success", "steps.version.outputs.status": "passed",
            "steps.version.outputs.version": VERSION,
        }
        for i in range(1, 6):
            self.values.update({f"steps.test{i}.outputs.status": "passed",
                                f"steps.test{i}.outcome": "success",
                                f"steps.test{i}.outputs.duration": str(i)})
        self.values.update({"steps.test6.outcome": "success", "steps.test6.outputs.status": "skipped",
                            "steps.test6.outputs.decision": "not_applicable_package_manager",
                            "steps.test6.outputs.duration": "0", "steps.test6.outputs.current_version": VERSION,
                            "steps.test6.outputs.latest_version": "not_applicable",
                            "steps.test6.outputs.next_installed_version": "not_applicable"})
        self.sequence = 0
        self.shell("uname", 'test "$*" = -m\nprintf "%s\\n" "$ARCH"\n')
        self.shell("bash", """
test "$*" = '.github/actions/apt-bootstrap/bootstrap.sh --packages flatpak bubblewrap dbus-x11 file'
exit "$APT_RC"
""")
        self.shell("timeout", """
case "$1" in --kill-after=5s|--kill-after=30s) ;; *) exit 98 ;; esac
case "$2" in 60s|120s|1500s) ;; *) exit 98 ;; esac
shift 2
exec "$@"
""")
        self.shell("dbus-run-session", 'test "$1" = --\nshift\nexec "$@"\n')
        # GNU chmod accepts -- after the mode; adapt only this local BSD fixture.
        self.shell("chmod", 'test "$1" = -R\ntest "$2" = u+w\ntest "$3" = --\nexec /bin/chmod -R u+w "$4"\n')
        self.python_tool("gcc", """
import os, pathlib, struct, sys
a = sys.argv[1:]
if int(os.environ["GCC_RC"]):
    sys.exit(int(os.environ["GCC_RC"]))
if a == ["--version"]:
    print("gcc (GCC) 16.2.0")
elif a == ["-dumpmachine"]:
    print(os.environ["TARGET"])
else:
    assert a == ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                 "/app/src/sdk-native-smoke.c", "-o", "/app/bin/sdk-native-smoke"], a
    app = pathlib.Path(os.environ["SDK_APP"])
    source = (app / "files/src/sdk-native-smoke.c").read_text()
    assert "value += 2 * i;" in source and "return value == expected ? 0 : 9;" in source
    if os.environ["WRITE_ELF"] == "1":
        header = bytearray(64)
        header[:6] = b"\\x7fELF\\x02\\x01"
        struct.pack_into("<HH", header, 16, 3, 183)
        (app / "files/bin/sdk-native-smoke").write_bytes(header)
""")
        self.python_tool("flatpak", """
import json, os, pathlib, subprocess, sys
a = sys.argv[1:]
e = os.environ
with open(e["CALLS"], "a") as log:
    log.write(json.dumps(a) + "\\n")
def emit(value, rc=0):
    print(value)
    sys.exit(int(rc))
if a == ["--default-arch"]:
    emit(e["ARCH"])
elif a == ["remote-add", "--user", "flathub", "https://flathub.org/repo/flathub.flatpakrepo"]:
    sys.exit(int(e["QUERY_RC"]))
elif a[:4] == ["remote-info", "--user", "--show-commit", "flathub"]:
    assert a[4] in (e["SDK_REF"], e["PLATFORM_REF"]) and len(a) == 5, a
    emit(e["REMOTE_SDK"] if a[4] == e["SDK_REF"] else e["REMOTE_PLATFORM"], e["QUERY_RC"])
elif a[:2] == ["install", "--user"]:
    assert a == ["install", "--user", "--assumeyes", "--noninteractive", "--no-related",
                 "--no-deps", "flathub", e["SDK_REF"], e["PLATFORM_REF"]], a
    sys.exit(int(e["INSTALL_RC"]))
elif a[:2] == ["info", "--user"]:
    assert a[-1] in (e["SDK_REF"], e["PLATFORM_REF"]), a
    sdk = a[-1] == e["SDK_REF"]
    if len(a) == 3:
        emit(e["SDK_INFO"], e["INFO_RC"])
    assert len(a) == 4, a
    values = {"--show-ref": e["INSTALLED_SDK_REF"] if sdk else e["INSTALLED_PLATFORM_REF"],
              "--show-commit": e["INSTALLED_SDK"] if sdk else e["INSTALLED_PLATFORM"],
              "--show-origin": e["ORIGIN"], "--show-metadata": e["SDK_METADATA"]}
    emit(values[a[2]], e["INFO_RC"])
elif a[:2] == ["build-init", "--arch=aarch64"]:
    assert a == ["build-init", "--arch=aarch64", e["SDK_APP"], "org.arm.EcosystemSdkSmoke",
                 "org.freedesktop.Sdk", "org.freedesktop.Platform", "26.08"], a
    if int(e["BUILD_INIT_RC"]):
        sys.exit(int(e["BUILD_INIT_RC"]))
    app = pathlib.Path(e["SDK_APP"])
    app.mkdir(parents=True, exist_ok=True)
    (app / "metadata").write_text(e["APP_METADATA"])
elif a[:2] == ["build", "--unshare=network"]:
    assert a[2] == e["SDK_APP"], a
    if int(e["BUILD_RC"]):
        sys.exit(int(e["BUILD_RC"]))
    if a[3:5] == ["sh", "-euc"]:
        assert len(a) == 6, a
        # Explicit synthetic SDK filesystem substitution; never native evidence.
        release = pathlib.Path(e["SDK_SCOPE"]) / "fixture-os-release"
        release.write_text(e["OS_RELEASE"])
        script = a[5].replace("/usr/lib/os-release", str(release)).replace(
            "cat " + str(release), 'cat "' + str(release) + '"').replace(
            ". " + str(release), '. "' + str(release) + '"')
        script = script.replace("= /usr/bin/gcc", '= "' + e["FIXTURE_BIN"] + '/gcc"')
        sys.exit(subprocess.run(["/bin/bash", "-euc", script], env=e).returncode)
    assert a[3:] in (["/app/bin/sdk-native-smoke", "42"], ["/app/bin/sdk-native-smoke", "43"]), a
    emit(e["RUN_OUTPUT"], e["RUN_RC"] if a[-1] == "42" else e["NEGATIVE_RC"])
else:
    raise AssertionError(a)
""")

    def shell(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -eu\n" + body)
        path.chmod(0o755)

    def python_tool(self, name, body):
        path = self.bin / name
        path.write_text("#!" + sys.executable + "\n" + body)
        path.chmod(0o755)

    def run_step(self, name, **overrides):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if self.values.get(term):
                    return str(self.values[term])
            return ""
        source = self.steps[name]["run"]
        rendered = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)
        env = {**self.env, **overrides}
        output, exports = Path(env["GITHUB_OUTPUT"]), Path(env["GITHUB_ENV"])
        output.write_text("")
        exports.write_text("")
        command = ["/bin/bash", "-e", "-o", "pipefail", "-c", rendered]
        result = subprocess.run(command, cwd=self.root, env=env, text=True, capture_output=True, timeout=30)
        pairs = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(pair) == 2 for pair in pairs))
        fields = dict(pairs)
        self.assertEqual(len(pairs), len(fields), "Duplicate output keys")
        if os.environ.get("WORKFLOW_EVIDENCE_ROOT"):
            self.sequence += 1
            folder = Path(os.environ["WORKFLOW_EVIDENCE_ROOT"]) / self._testMethodName / str(self.sequence)
            folder.mkdir(parents=True, exist_ok=False)
            for filename, value in (("source.sh", source), ("rendered.sh", rendered),
                                    ("stdout.txt", result.stdout), ("stderr.txt", result.stderr),
                                    ("github-output.txt", output.read_text()), ("github-env.txt", exports.read_text()),
                                    ("exit.txt", str(result.returncode) + "\n"),
                                    ("workflow.sha256", hashlib.sha256(WORKFLOW.read_bytes()).hexdigest() + "\n")):
                (folder / filename).write_text(value)
            for filename, value in (("env.json", env), ("values.json", self.values), ("command.json", command)):
                (folder / filename).write_text(json.dumps(value, indent=2) + "\n")
            fixtures = folder / "fixtures"
            fixtures.mkdir()
            for path in self.bin.iterdir():
                if not path.is_symlink():
                    (fixtures / path.name).write_bytes(path.read_bytes())
        return result, fields

    def accept(self, step):
        result, fields = self.run_step(step)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.values[f"steps.{step}.outcome"] = "success"
        self.values.update({f"steps.{step}.outputs.{key}": value for key, value in fields.items()})
        for line in Path(self.env["GITHUB_ENV"]).read_text().splitlines():
            key, value = line.split("=", 1)
            self.env[key] = value
        return fields

    def reject(self, step, **faults):
        result, fields = self.run_step(step, **faults)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", fields["install_status" if step == "install" else "status"])
        self.assertRegex(fields["duration"], r"^[0-9]+$")
        self.assertNotIn("version", fields)
        return fields

    def fresh_install(self):
        shutil.rmtree(self.scope)

    def test_complete_fixture_pipeline_and_real_policy(self):
        self.fresh_install()
        install = self.accept("install")
        self.assertEqual("flatpak", install["installation_method"])
        version = self.accept("version")
        self.assertEqual(VERSION, version["version"])
        for i in range(1, 6):
            self.assertEqual("passed", self.accept(f"test{i}")["status"])
        regression = self.accept("test6")
        totals = self.accept("summary")
        self.assertEqual(("5", "0", "1", "0", "success", "passing"),
                         tuple(totals[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status", "badge_status")))
        details = [{"name": self.steps[f"test{i}"]["name"], "status": "passed"} for i in range(1, 6)]
        details.append({"name": self.steps["test6"]["name"], **regression})
        self.assertEqual("success", policy.validate_six_test_result(
            details=details, **{key: int(totals[key]) for key in ("passed", "failed", "skipped", "core_failed")},
            decision=regression["decision"]))
        self.accept("cleanup")
        self.assertFalse(self.scope.exists())

    def test_install_failures_and_ref_commit_races(self):
        cases = ({"APT_RC": "100"}, {"INSTALL_RC": "1"}, {"QUERY_RC": "23"},
                 {"ARCH": "x86_64"}, {"REMOTE_SDK": ""}, {"REMOTE_PLATFORM": "abc"},
                 {"REMOTE_SDK": "a" * 63}, {"REMOTE_SDK": "A" * 64},
                 {"INSTALLED_SDK": "0" * 64}, {"INSTALLED_PLATFORM": "0" * 64},
                 {"INSTALLED_SDK_REF": SDK_REF.replace(".Sdk/", ".Sdk.Extension.rust-stable/")},
                 {"INSTALLED_PLATFORM_REF": PLATFORM_REF.replace("aarch64", "x86_64")},
                 {"ORIGIN": "untrusted"})
        for faults in cases:
            with self.subTest(faults=faults):
                if self.scope.exists():
                    self.fresh_install()
                self.reject("install", **faults)

    def test_version_is_the_sdk_build_not_the_flatpak_cli(self):
        self.assertEqual(VERSION, self.accept("version")["version"])
        for info in ("", "Flatpak 1.14.6\n", INFO.replace("org.freedesktop.Sdk", "org.freedesktop.Sdk.Debug"),
                     INFO.replace("aarch64", "x86_64"), INFO.replace("26.08.0", "25.08.9"),
                     INFO.replace("freedesktop-sdk-26.08.0", "1.14.6"), INFO + "Version: freedesktop-sdk-26.08.0\n",
                     INFO.replace(SDK_COMMIT, "0" * 64), INFO.replace("Origin: flathub", "Origin: other")):
            with self.subTest(info=info):
                self.reject("version", SDK_INFO=info)
        self.reject("version", INFO_RC="1")

    def test_metadata_requires_actual_base_sdk_and_matching_platform(self):
        for field in ("SDK_METADATA", "APP_METADATA"):
            for value in ("", METADATA.replace("aarch64", "x86_64"),
                          METADATA.replace("26.08", "25.08"),
                          METADATA.replace(".Sdk", ".Sdk.Extension.rust-stable")):
                with self.subTest(field=field, value=value):
                    self.reject("test1", **{field: value})
        self.reject("test1", BUILD_INIT_RC="1")
        self.reject("test1", INSTALLED_PLATFORM="f" * 64)

    def test_actual_inner_sdk_shell_checks_os_identity_and_compiler(self):
        self.accept("test2")
        for faults in ({"OS_RELEASE": OS_RELEASE.replace("org.freedesktop.platform", "ubuntu")},
                       {"OS_RELEASE": OS_RELEASE.replace("26.08", "25.08")},
                       {"OS_RELEASE": OS_RELEASE.replace("Freedesktop SDK", "Ubuntu")},
                       {"ARCH": "x86_64"}, {"TARGET": "x86_64-linux-gnu"},
                       {"GCC_RC": "1"}, {"BUILD_RC": "1"}):
            with self.subTest(faults=faults):
                self.reject("test2", **faults)

    def test_compiler_failure_empty_output_and_stale_binary_fail(self):
        self.reject("test3", GCC_RC="1")
        self.reject("test3", WRITE_ELF="0")
        self.reject("test3", BUILD_RC="1")
        self.app.joinpath("files/bin/sdk-native-smoke").write_bytes(b"stale")
        self.reject("test3")

    def test_real_elf_parser_rejects_non_arm64_and_non_executable_headers(self):
        binary = self.app / "files/bin/sdk-native-smoke"
        header = bytearray(64)
        header[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<HH", header, 16, 3, 183)
        binary.write_bytes(header)
        self.accept("test4")
        mutations = [b"", bytes(header[:32]), b"not an ELF" + bytes(64)]
        for offset, value in ((4, 1), (5, 2), (16, 1), (18, 62)):
            changed = bytearray(header)
            changed[offset] = value
            mutations.append(bytes(changed))
        for content in mutations:
            with self.subTest(header=content):
                binary.write_bytes(content)
                self.reject("test4")

    def test_bad_actual_application_results_and_wrong_negative_exit_fail(self):
        self.accept("test5")
        for faults in ({"RUN_RC": "9"}, {"RUN_RC": "124"}, {"RUN_OUTPUT": ""},
                       {"RUN_OUTPUT": RUN_OUTPUT.replace("42", "43")},
                       {"RUN_OUTPUT": RUN_OUTPUT.replace("64", "32")},
                       {"NEGATIVE_RC": "0"}, {"NEGATIVE_RC": "1"}, {"NEGATIVE_RC": "124"}):
            with self.subTest(faults=faults):
                self.reject("test5", **faults)

    def test_prerequisite_guards_prevent_false_passes(self):
        for step, previous in (("version", "install"), ("test1", "version"),
                               ("test2", "test1"), ("test3", "test2"), ("test4", "test3"), ("test5", "test4")):
            for outcome in ("failure", "cancelled", "skipped", ""):
                with self.subTest(step=step, outcome=outcome):
                    self.values[f"steps.{previous}.outcome"] = outcome
                    self.reject(step)
            self.values[f"steps.{previous}.outcome"] = "success"

    def test_each_core_status_outcome_and_duration_is_strict(self):
        original = dict(self.values)
        for i in range(1, 6):
            for field, value in (("outputs.status", ""), ("outputs.status", "skipped"),
                                 ("outputs.status", "failed"), ("outcome", "failure"), ("outcome", "cancelled"),
                                 ("outcome", "skipped"), ("outcome", ""), ("outputs.duration", ""),
                                 ("outputs.duration", "bad"), ("outputs.duration", "-1"),
                                 ("outputs.duration", "1.5"), ("outputs.duration", "1000000")):
                with self.subTest(step=i, field=field, value=value):
                    self.values = dict(original)
                    self.values[f"steps.test{i}.{field}"] = value
                    skip = self.accept("test6")
                    self.assertEqual("baseline_failed", skip["decision"])
                    result, summary = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("4", "1", "1", "1", "failure"),
                                     tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed", "overall_status")))
        self.values = dict(original)
        self.values["steps.test1.outputs.duration"] = "08"
        self.accept("test6")
        self.assertEqual("22", self.accept("summary")["duration"])

    def test_baseline_failures_have_policy_accepted_decisions(self):
        for install_failed in (False, True):
            self.values["steps.install.outcome"] = "failure" if install_failed else "success"
            for i in range(1, 6):
                self.values[f"steps.test{i}.outputs.status"] = "failed"
                self.values[f"steps.test{i}.outcome"] = "failure"
            regression = self.accept("test6")
            self.assertEqual("baseline_install_failed" if install_failed else "baseline_failed", regression["decision"])
            result, summary = self.run_step("summary")
            self.assertNotEqual(0, result.returncode)
            details = [{"name": self.steps[f"test{i}"]["name"], "status": "failed"} for i in range(1, 6)]
            details.append({"name": self.steps["test6"]["name"], **regression})
            self.assertEqual("failure", policy.validate_six_test_result(
                details=details, **{key: int(summary[key]) for key in ("passed", "failed", "skipped", "core_failed")},
                decision=regression["decision"]))

    def test_install_and_version_prerequisites_cannot_be_masked_by_skip(self):
        original = dict(self.values)
        cases = (("steps.install.outcome", "failure"), ("steps.install.outputs.install_status", "failed"),
                 ("steps.install.outputs.installation_method", "apt"), ("steps.version.outcome", "failure"),
                 ("steps.version.outputs.status", "failed"), ("steps.version.outputs.version", ""),
                 ("steps.version.outputs.version", "unknown"), ("steps.version.outputs.version", "1.14.6"))
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.values = dict(original)
                self.values[key] = value
                skip = self.accept("test6")
                self.assertNotEqual("not_applicable_package_manager", skip["decision"])
                result, fields = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failure", fields["overall_status"])

    def test_test6_requires_exact_skip_outcome_and_candidate_semantics(self):
        original = dict(self.values)
        for field, value in (("status", "passed"), ("status", "failed"), ("decision", "baseline_failed"),
                             ("decision", "baseline_install_failed"), ("decision", "not_configured"),
                             ("duration", "1"), ("duration", ""), ("current_version", "1.14.6"),
                             ("latest_version", "26.08.1"), ("next_installed_version", "26.08.1")):
            with self.subTest(field=field, value=value):
                self.values = dict(original)
                self.values[f"steps.test6.outputs.{field}"] = value
                result, fields = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("5", "1", "0", "0"), tuple(fields[k] for k in ("passed", "failed", "skipped", "core_failed")))
        for outcome in ("failure", "cancelled", "skipped", ""):
            self.values = dict(original)
            self.values["steps.test6.outcome"] = outcome
            self.assertNotEqual(0, self.run_step("summary")[0].returncode)

    def test_actual_auditor_sees_outputs_and_only_approved_decisions(self):
        for step in ("version", "test1", "test2", "test3", "test4", "test5"):
            for field in ("status", "duration"):
                self.assertTrue(audit._step_emits_output(ROOT, self.steps[step], field), (step, field))
        for field in ("version", "package_version"):
            self.assertTrue(audit._step_emits_output(ROOT, self.steps["version"], field))
        for field in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status"):
            self.assertTrue(audit._step_emits_output(ROOT, self.steps["summary"], field), field)
        self.assertEqual({("not_applicable_package_manager", "skipped"), ("baseline_failed", "skipped"),
                          ("baseline_install_failed", "skipped")},
                         set(audit._step_literal_pairs(ROOT, self.steps["test6"])))
        self.assertEqual(1, len([step for step in self.job["steps"] if "uses" in step]))
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        for name in ("version", "test1", "test2", "test3", "test4", "test5", "test6", "summary", "cleanup"):
            self.assertEqual("always()", self.steps[name]["if"])

    def test_owned_cleanup_refuses_wrong_owner_or_symlink(self):
        (self.scope / "owner").write_text("someone else\n")
        self.assertNotEqual(0, self.run_step("cleanup")[0].returncode)
        self.assertTrue(self.scope.exists())
        shutil.rmtree(self.scope)
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "keep"
        sentinel.write_text("untouched")
        self.scope.symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(0, self.run_step("cleanup")[0].returncode)
        self.assertEqual("untouched", sentinel.read_text())
        self.scope.unlink()
        self.accept("cleanup")


if __name__ == "__main__":
    unittest.main()
