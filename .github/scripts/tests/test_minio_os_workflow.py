"""Exercise MinIO acquisition integrity and the unchanged smoke failure gates."""

import hashlib
from collections import Counter
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

import package_observation_migration_audit as audit  # noqa: E402


WORKFLOW = ROOT / ".github/workflows/test-minio-os.yml"
VERSION = "RELEASE.2025-09-07T16-13-09Z"
SHA256 = "5c83cd2cf151717ba0243f73e1c7802ff36e272b67144bdd7f1f7d684fd6f03d"
CANDIDATE = "RELEASE.2025-10-15T17-29-55Z"
CANDIDATE_COMMIT = "9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a"
ASSET_URL = f"https://github.com/minio/minio/releases/download/{VERSION}/minio.linux-arm64.{VERSION}"
JOB = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-minio-os"]
STEPS = {step["id"]: step for step in JOB["steps"] if "id" in step}


def render(script, values):
    def expression(match):
        for term in match[1].split("||"):
            term = term.strip()
            if term.startswith("'") and term.endswith("'"):
                return term[1:-1]
            if term.isdigit():
                return term
            if values.get(term):
                return str(values[term])
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)


class MinioOsWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="minio-os-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.fixture = self.root / "artifact"
        self.fixture.write_bytes(b"controlled MinIO download fixture\n")
        self.digest = hashlib.sha256(self.fixture.read_bytes()).hexdigest()
        self.env = dict(os.environ, HOME=str(self.root), RUNNER_TEMP=str(self.root), TMPDIR=str(self.root),
                        GITHUB_OUTPUT=str(self.root / "output"),
                        GITHUB_PATH=str(self.root / "path"),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        PYTHON=sys.executable,
                        FIXTURE=str(self.fixture), EXPECTED_URL=ASSET_URL)
        self.values = {"steps.metadata.outputs.current_version": VERSION,
                       "steps.version.outputs.version": VERSION}
        if sys.platform == "darwin":
            self.write_script("bin/sha256sum", 'exec shasum --algorithm 256 "$@"')
        self.write_script(".github/actions/apt-bootstrap/bootstrap.sh", 'exit "${APT_RC:-0}"')
        self.write_script(".github/scripts/download-with-fallback.sh", '''
test "$#" = 2
test "$2" = "$EXPECTED_URL"
test "${DOWNLOAD_RC:-0}" = 0
cp "$FIXTURE" "$1"
if [ "${CORRUPT:-0}" = 1 ]; then printf 'corrupt' >> "$1"; fi
''')
        self.write_script("bin/file", 'echo "${FILE_OUTPUT:-ELF 64-bit ARM aarch64}"')
        self.write_script("bin/minio", r'''
case "$*" in
  --version) printf 'minio version %s\n' "${MINIO_VERSION:-RELEASE.2025-09-07T16-13-09Z}" ;;
  --help) printf '%s\n' "${TOP_LEVEL_HELP:-NAME:
  minio - High Performance Object Storage
USAGE:
  minio [FLAGS] COMMAND [ARGS...]
COMMANDS:
  server  start object storage server}" ;;
  'server --help')
    if [ "${HELP_MATCH:-1}" = 1 ]; then echo 'NAME: minio server'; fi
    "$PYTHON" -c 'print("details\n" * 20000 + "end-of-help")' ;;
  server*)
    printf '%s\n' "$$" > "$SERVER_PID_FILE"
    if [ "${STARTUP_RC:-0}" != 0 ]; then
      echo 'MinIO: <ERROR> Unable to start the server: address already in use'
      exit "$STARTUP_RC"
    fi
    exec "$PYTHON" -c 'import time; time.sleep(120)' ;;
  *) exit 1 ;;
esac
exit "${MINIO_RC:-0}"
''')

    def write_script(self, relative, source):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + source + "\n")
        path.chmod(0o755)

    def run_step(self, name, fixture_checksum=False, **overrides):
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        if name in ("test5", "test6"):
            (self.root / "server.pid").unlink(missing_ok=True)
        script = render(STEPS[name]["run"], self.values)
        for log in ("minio-help.log", "minio-server-help.log"):
            script = script.replace(f"/tmp/{log}", shlex.quote(str(self.root / log)))
        if fixture_checksum:
            script = script.replace(SHA256, self.digest)
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **overrides),
                                text=True, capture_output=True, timeout=30)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def test_exact_baseline_official_asset_and_checksum_are_pinned(self):
        self.assertIn(f"current_version={VERSION}", STEPS["metadata"]["run"])
        self.assertIn('URL="https://github.com/minio/minio/releases/download/${VERSION}/minio.linux-arm64.${VERSION}"', STEPS["install"]["run"])
        self.assertIn(f'SHA256="{SHA256}"', STEPS["install"]["run"])
        self.assertIn("sha256sum --check --strict", STEPS["install"]["run"])
        self.assertNotIn("dl.min.io", WORKFLOW.read_text())
        self.assertNotIn("/usr/local/bin", STEPS["install"]["run"])
        self.assertNotIn("|| true", STEPS["install"]["run"])
        self.assertIsNotNone(shutil.which("sha256sum"))

    def test_verified_download_is_executable_and_published_from_runner_temp(self):
        result, outputs = self.run_step("install", fixture_checksum=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("success", outputs["install_status"])
        directory = Path(self.env["GITHUB_PATH"]).read_text().strip()
        binary = Path(directory) / "minio"
        self.assertEqual(self.root, binary.parent.parent)
        self.assertTrue(os.access(binary, os.X_OK))
        self.assertEqual(self.fixture.read_bytes(), binary.read_bytes())

    def test_dependency_download_and_checksum_failures_cannot_publish_install(self):
        for overrides in ({"APT_RC": "1"}, {"DOWNLOAD_RC": "1"}, {"CORRUPT": "1"}):
            with self.subTest(overrides=overrides):
                result, outputs = self.run_step("install", fixture_checksum=True, **overrides)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("install_status", outputs)
                self.assertFalse(Path(self.env["GITHUB_PATH"]).exists())
                self.assertFalse(any(os.access(path, os.X_OK) for path in self.root.glob("minio-os.*/minio")))

    def test_real_pinned_checksum_rejects_an_untrusted_artifact(self):
        result, outputs = self.run_step("install")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("install_status", outputs)
        self.assertFalse(Path(self.env["GITHUB_PATH"]).exists())

    def test_architecture_and_exact_version_assertions_remain_enforced(self):
        for step, overrides in (("test1", {}), ("test1", {"FILE_OUTPUT": "ELF 64-bit x86-64"}),
                                ("test2", {}), ("test2", {"MINIO_VERSION": "RELEASE.other"}),
                                ("test2", {"MINIO_RC": "1"})):
            with self.subTest(step=step, overrides=overrides):
                result, outputs = self.run_step(step, **overrides)
                self.assertEqual(not overrides, result.returncode == 0, result.stderr)
                if overrides:
                    self.assertNotEqual("passed", outputs.get("status"))
                else:
                    self.assertEqual("passed", outputs["status"])

    def test_server_help_drains_output_and_preserves_match_and_producer_failure_checks(self):
        for overrides in ({}, {"HELP_MATCH": "0"}, {"MINIO_RC": "1"}):
            with self.subTest(overrides=overrides):
                result, outputs = self.run_step("test4", **overrides)
                self.assertEqual(not overrides, result.returncode == 0, result.stderr)
                self.assertEqual("failed" if overrides else "passed", outputs["status"])
                self.assertTrue((self.root / "minio-server-help.log").read_text().endswith("end-of-help\n"))

    def test_top_level_help_requires_success_and_all_structured_headers(self):
        cases = ({}, {"MINIO_RC": "17"},
                 {"MINIO_RC": "17", "TOP_LEVEL_HELP": "MinIO: <ERROR> failed to initialize"},
                 {"TOP_LEVEL_HELP": "MinIO: <ERROR> failed to initialize"},
                 {"TOP_LEVEL_HELP": "NAME:\nUSAGE:"},
                 {"TOP_LEVEL_HELP": "USAGE:\nCOMMANDS:"},
                 {"TOP_LEVEL_HELP": "NAME:\nCOMMANDS:"},
                 {"TOP_LEVEL_HELP": "not help NAME: USAGE: COMMANDS:"})
        for overrides in cases:
            with self.subTest(overrides=overrides):
                result, outputs = self.run_step("test3", **overrides)
                self.assertEqual(not overrides, result.returncode == 0, result.stdout + result.stderr)
                self.assertEqual("failed" if overrides else "passed", outputs["status"])
                self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_missing_baseline_results_cannot_pass_summary(self):
        result, outputs = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("6", outputs["failed"])
        self.assertEqual("5", outputs["core_failed"])
        self.assertEqual("failure", outputs["overall_status"])

    def test_summary_preserves_each_test_failure_gate(self):
        self.values.update({f"steps.test{i}.outputs.status": "passed" for i in range(1, 7)})
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", outputs["passed"])
        self.assertEqual("0", outputs["failed"])
        self.assertEqual("success", outputs["overall_status"])
        for number in range(1, 7):
            with self.subTest(test=number):
                key = f"steps.test{number}.outputs.status"
                self.values[key] = "failed"
                result, outputs = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("failure", outputs["overall_status"])
                self.assertEqual("1" if number < 6 else "0", outputs["core_failed"])
                self.values[key] = "passed"

    def candidate_stubs(self):
        self.values.update({f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)})
        self.write_script("bin/uname", 'echo "${HOST_ARCH:-aarch64}"')
        self.write_script("bin/timeout", 'shift\nexec "$@"')
        self.write_script("bin/sleep", "exit 0")
        self.write_script("bin/curl", '''
"$PYTHON" -c 'import os, time; from pathlib import Path
for _ in range(100):
    if Path(os.environ["SERVER_PID_FILE"]).exists():
        break
    time.sleep(0.01)
time.sleep(0.02)'
printf "%s" "${HEALTH_HTTP:-200}"
''')
        self.write_script("bin/ss", r'''
test "$*" = "-H -4 -ltnp sport = :${LISTENER_PORT:-19300}"
test "${SS_RC:-0}" = 0
PID=$(cat "$SERVER_PID_FILE")
ADDRESS=127.0.0.1:${LISTENER_PORT:-19300}
case "${LISTENER_MODE:-owned}" in
  occupied) PID=$((PID + 1)) ;;
  pid_prefix) PID="${PID}0" ;;
  pid_suffix) PID="9${PID}" ;;
  no_pid) echo "LISTEN 0 4096 $ADDRESS 0.0.0.0:*"; exit 0 ;;
  no_listener) exit 0 ;;
  wrong_address) ADDRESS=127.0.0.2:${LISTENER_PORT:-19300} ;;
  wrong_port) ADDRESS=127.0.0.1:19301 ;;
esac
printf 'LISTEN 0 4096 %s 0.0.0.0:* users:(("minio",pid=%s,fd=7))\n' "$ADDRESS" "$PID"
''')
        self.write_script("bin/git", r'''
test -z "${GH_TOKEN+x}"
test -z "${GITHUB_TOKEN+x}"
case "$1" in
  clone)
    test "${CLONE_RC:-0}" = 0
    test "$2 $3 $4 $5 $6" = "--depth 1 --branch $NEXT_VERSION https://github.com/minio/minio.git"
    mkdir -p "$7" ;;
  rev-parse) printf '%s\n' "${SOURCE_COMMIT:-$NEXT_COMMIT}" ;;
  *) exit 1 ;;
esac
''')
        self.write_script("bin/go", r'''
test -z "${GH_TOKEN+x}"
test -z "${GITHUB_TOKEN+x}"
test "$GOTOOLCHAIN" = go1.24.8
test "$GOMAXPROCS/$GOFLAGS" = 2/-p=2
case "$1" in
  env)
    case "$2" in
      GOVERSION) echo "${GO_VERSION:-go1.24.8}" ;;
      GOHOSTOS) echo linux ;;
      GOHOSTARCH) echo arm64 ;;
      *) exit 1 ;;
    esac ;;
  run)
    test "${FLAGS_RC:-0}" = 0
    test "$MINIO_RELEASE" = RELEASE
    test "$2" = buildscripts/gen-ldflags.go
    echo '-s -w' ;;
  build)
    test "${BUILD_RC:-0}" = 0
    test "$CGO_ENABLED/$GOOS/$GOARCH" = 0/linux/arm64
    test "$*" = 'build -mod=readonly -tags kqueue -trimpath --ldflags -s -w -o minio .'
    mkdir -p "$GOMODCACHE/read-only"
    touch "$GOMODCACHE/read-only/module"
    chmod a-w "$GOMODCACHE/read-only"
    cp "$MOCK_CANDIDATE" minio ;;
  *) exit 1 ;;
esac
''')
        self.write_script("candidate", r'''
test -z "${GH_TOKEN+x}"
test -z "${GITHUB_TOKEN+x}"
case "$*" in
  --version)
    printf 'minio version %s (commit-id=%s)\nRuntime: go1.24.8 linux/arm64\n' "${CANDIDATE_VERSION:-$NEXT_VERSION}" "${REPORTED_COMMIT:-$NEXT_COMMIT}" ;;
  'server --help')
    test "${HELP_RC:-0}" = 0
    echo "${CANDIDATE_HELP:-NAME: minio server}" ;;
  server*)
    printf '%s\n' "$$" > "$SERVER_PID_FILE"
    if [ "${STARTUP_RC:-0}" != 0 ]; then
      echo 'MinIO: <ERROR> Unable to start the server: address already in use'
      exit "$STARTUP_RC"
    fi
    exec "$PYTHON" -c 'import time; time.sleep(120)' ;;
  *) exit 1 ;;
esac
''')
        self.env["MOCK_CANDIDATE"] = str(self.root / "candidate")
        self.env["SERVER_PID_FILE"] = str(self.root / "server.pid")

    def test_baseline_health_requires_its_own_live_listener(self):
        self.candidate_stubs()
        for overrides in ({}, {"LISTENER_MODE": "occupied"}, {"LISTENER_MODE": "pid_prefix"},
                          {"LISTENER_MODE": "pid_suffix"}, {"LISTENER_MODE": "no_pid"},
                          {"LISTENER_MODE": "no_listener"}, {"LISTENER_MODE": "wrong_address"},
                          {"LISTENER_MODE": "wrong_port"}, {"SS_RC": "1"},
                          {"STARTUP_RC": "17"}, {"HEALTH_HTTP": "503"}):
            with self.subTest(overrides=overrides):
                result, outputs = self.run_step("test5", LISTENER_PORT="9001", **overrides)
                self.assertEqual(not overrides, result.returncode == 0, result.stdout + result.stderr)
                self.assertEqual("failed" if overrides else "passed", outputs["status"])
                self.assertRegex(outputs["duration"], r"^[0-9]+$")

    def test_source_only_candidate_requires_exact_identity_build_and_live_health(self):
        self.candidate_stubs()
        result, outputs = self.run_step("test6", GH_TOKEN="test-only-sentinel", GITHUB_TOKEN="test-only-sentinel")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.assertEqual("next_install_validated", outputs["decision"])
        self.assertEqual(CANDIDATE, outputs["next_installed_version"])
        self.assertIn(CANDIDATE_COMMIT, outputs["comparison"])
        self.assertIn("HTTP 200", result.stdout)
        self.assertFalse(list(self.root.glob("minio-os-next.*")))

    def test_regression_outputs_are_recognized_by_repository_auditor(self):
        for output in ("status", "duration", "decision"):
            with self.subTest(output=output):
                self.assertTrue(audit._step_emits_output(ROOT, STEPS["test6"], output))

    def test_regression_outputs_emit_once_on_success_failure_and_baseline_guard(self):
        self.candidate_stubs()
        expected_keys = {"current_version", "latest_version", "next_installed_version", "decision",
                         "regression_result", "comparison", "status", "duration"}
        for baseline, overrides, expected in (("passed", {}, "passed"),
                                              ("passed", {"BUILD_RC": "1"}, "failed"),
                                              ("passed", {"LISTENER_MODE": "occupied"}, "failed"),
                                              ("failed", {}, "skipped")):
            with self.subTest(baseline=baseline, overrides=overrides):
                self.values["steps.test1.outputs.status"] = baseline
                result, outputs = self.run_step("test6", **overrides)
                self.assertEqual(expected != "failed", result.returncode == 0, result.stdout + result.stderr)
                self.assertEqual(expected, outputs["status"])
                counts = Counter(line.split("=", 1)[0]
                                 for line in Path(self.env["GITHUB_OUTPUT"]).read_text().splitlines())
                self.assertEqual({key: 1 for key in expected_keys}, counts)
                self.assertFalse(list(self.root.glob("minio-os-next.*")))

    def test_candidate_health_from_occupied_port_or_wrong_pid_cannot_pass(self):
        self.candidate_stubs()
        for overrides in ({"LISTENER_MODE": "occupied"}, {"LISTENER_MODE": "pid_prefix"},
                          {"LISTENER_MODE": "pid_suffix"}, {"LISTENER_MODE": "no_pid"},
                          {"LISTENER_MODE": "no_listener"}, {"LISTENER_MODE": "wrong_address"},
                          {"LISTENER_MODE": "wrong_port"}, {"SS_RC": "1"}):
            with self.subTest(overrides=overrides):
                result, outputs = self.run_step("test6", HEALTH_HTTP="200", **overrides)
                self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertEqual("failed", outputs["status"])
                self.assertEqual("next_install_failed", outputs["decision"])
                self.assertEqual("not_installed", outputs["next_installed_version"])
                self.assertFalse(list(self.root.glob("minio-os-next.*")))

    def test_candidate_startup_failure_cannot_accept_existing_healthy_server(self):
        self.candidate_stubs()
        result, outputs = self.run_step("test6", STARTUP_RC="17", HEALTH_HTTP="200",
                                        LISTENER_MODE="occupied")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", outputs["status"])
        self.assertEqual("next_install_failed", outputs["decision"])
        self.assertIn("Unable to start the server", result.stdout)
        self.assertFalse(list(self.root.glob("minio-os-next.*")))

    def test_candidate_faults_emit_failed_evidence_and_keep_summary_red(self):
        self.candidate_stubs()
        for overrides in ({"CLONE_RC": "1"}, {"SOURCE_COMMIT": "wrong"}, {"BUILD_RC": "1"},
                          {"FLAGS_RC": "1"}, {"GO_VERSION": "go1.22.0"}, {"HOST_ARCH": "x86_64"},
                          {"FILE_OUTPUT": "ELF x86-64"}, {"CANDIDATE_VERSION": VERSION},
                          {"REPORTED_COMMIT": "wrong"}, {"HELP_RC": "1"},
                          {"CANDIDATE_HELP": "unrelated"}, {"HEALTH_HTTP": "503"}):
            with self.subTest(overrides=overrides):
                result, outputs = self.run_step("test6", **overrides)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])
                self.assertEqual("next_install_failed", outputs["decision"])
                self.assertEqual("not_installed", outputs["next_installed_version"])
                self.assertRegex(outputs["duration"], r"^[0-9]+$")
                self.assertFalse(list(self.root.glob("minio-os-next.*")))
                self.values["steps.test6.outputs.status"] = outputs["status"]
                summary, counts = self.run_step("summary")
                self.assertNotEqual(0, summary.returncode)
                self.assertEqual("failure", counts["overall_status"])

    def test_regression_cannot_claim_package_manager_or_missing_newer_release(self):
        self.assertIn(f'NEXT_VERSION="{CANDIDATE}"', STEPS["test6"]["run"])
        self.assertIn(f'NEXT_COMMIT="{CANDIDATE_COMMIT}"', STEPS["test6"]["run"])
        for forbidden in ("not_applicable_package_manager", "no_newer_stable_available", "dl.min.io", "uses: actions/setup-go"):
            self.assertNotIn(forbidden, WORKFLOW.read_text())
        for number in range(1, 6):
            self.candidate_stubs()
            self.values[f"steps.test{number}.outputs.status"] = "failed"
            result, outputs = self.run_step("test6", CLONE_RC="1")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("baseline_failed", outputs["decision"])
            self.assertEqual("skipped", outputs["status"])
            self.values["steps.test6.outputs.status"] = outputs["status"]
            self.values["steps.test6.outputs.decision"] = outputs["decision"]
            summary, counts = self.run_step("summary")
            self.assertNotEqual(0, summary.returncode)
            self.assertEqual("failure", counts["overall_status"])
            self.assertEqual("1", counts["skipped"])

    def test_missing_invalid_or_unearned_skipped_candidate_cannot_pass_summary(self):
        self.values.update({f"steps.test{i}.outputs.status": "passed" for i in range(1, 6)})
        for status in ("", "unknown", "skipped", "deferred"):
            self.values["steps.test6.outputs.status"] = status
            self.values["steps.test6.outputs.decision"] = "baseline_failed"
            result, counts = self.run_step("summary")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failure", counts["overall_status"])
            self.assertEqual("1", counts["failed"])
            self.assertEqual("0", counts["skipped"])


def native_smoke():
    """Run on an isolated Linux Arm64 host without installing system packages."""
    if sys.platform != "linux" or os.uname().machine != "aarch64":
        raise RuntimeError("Native smoke requires Linux aarch64")
    for port in (19300, 19301):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    for tool in ("curl", "wget", "file", "sha256sum", "git", "ss"):
        if not shutil.which(tool):
            raise RuntimeError(f"Required tool unavailable: {tool}")

    with tempfile.TemporaryDirectory(prefix="minio-os-native-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir()
        output = root / "output"
        github_path = root / "path"
        env = dict(os.environ, HOME=str(home), RUNNER_TEMP=str(root), TMPDIR=str(root),
                   GITHUB_OUTPUT=str(output), GITHUB_PATH=str(github_path))
        env.pop("GH_TOKEN", None)
        env.pop("GITHUB_TOKEN", None)
        archive = root / "go.tar.gz"
        subprocess.run(["curl", "-fsSL", "--retry", "3", "--connect-timeout", "20", "--max-time", "180",
                        "-o", str(archive), "https://go.dev/dl/go1.24.8.linux-arm64.tar.gz"], check=True)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != "38ac33b4cfa41e8a32132de7a87c6db49277ab5c0de1412512484db1ed77637e":
            raise RuntimeError("Native Go toolchain checksum mismatch")
        subprocess.run(["tar", "-xzf", str(archive), "-C", str(root)], check=True)
        env["PATH"] = str(root / "go/bin") + os.pathsep + env["PATH"]
        values = {}
        failures = []
        print(f"Native architecture: {os.uname().machine}", flush=True)
        print(f"Isolated workspace: {root}", flush=True)
        for name in ("metadata", "install", "version", "test1", "test2", "test3", "test4", "test5", "test6", "summary"):
            script = render(STEPS[name]["run"], values)
            # The host dependencies are preflighted; do not mutate shared apt state.
            script = script.replace('bash .github/actions/apt-bootstrap/bootstrap.sh --packages "wget curl file iproute2"',
                                    "command -v wget curl file sha256sum ss")
            script = script.replace('bash .github/actions/apt-bootstrap/bootstrap.sh --packages "git golang-go iproute2"',
                                    "command -v git go ss")
            for log in ("minio-help.log", "minio-server-help.log"):
                script = script.replace(f"/tmp/{log}", shlex.quote(str(root / log)))
            script = script.replace("--address 127.0.0.1:9001 --console-address 127.0.0.1:9002",
                                    "--address 127.0.0.1:19300 --console-address 127.0.0.1:19301")
            script = script.replace("127.0.0.1:9001", "127.0.0.1:19300")
            script = script.replace("sport = :9001", "sport = :19300")
            if name == "test4":
                script = script.replace("else\n", 'else\n  printf "MinIO/tee/grep exit statuses: %s\\n" "${PIPESTATUS[*]}"\n', 1)
            output.write_text("")
            result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=1500)
            print(f"{name}: exit={result.returncode}", flush=True)
            print(result.stdout, end="", flush=True)
            if result.returncode:
                print(result.stderr, end="", flush=True)
                failures.append(name)
                if not STEPS[name].get("continue-on-error") and name != "summary":
                    raise RuntimeError(f"Native workflow step failed: {name}")
            outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
            print(outputs, flush=True)
            values.update({f"steps.{name}.outputs.{key}": value for key, value in outputs.items()})
            if name == "install":
                directory = github_path.read_text().strip()
                env["PATH"] = directory + os.pathsep + env["PATH"]
                binary = Path(directory) / "minio"
                digest = hashlib.sha256(binary.read_bytes()).hexdigest()
                if digest != SHA256:
                    raise RuntimeError("Native artifact checksum mismatch")
                print(f"Verified SHA256: {digest}", flush=True)
                subprocess.run(["file", str(binary)], check=True)
                subprocess.run([str(binary), "--version"], env=env, check=True)
            if name.startswith("test") and outputs.get("status") != "passed":
                if name not in failures:
                    failures.append(name)
        if failures:
            raise RuntimeError(f"Native workflow failures: {failures}")
        if outputs.get("passed") != "6" or outputs.get("failed") != "0" or outputs.get("overall_status") != "success":
            raise RuntimeError("Native summary is not successful")
    print("Native smoke passed; isolated workspace removed.", flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--native"]:
        native_smoke()
    else:
        unittest.main()
