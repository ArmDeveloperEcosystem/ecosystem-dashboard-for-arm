"""Exercise release identity and failure reporting from the actual workflow bodies."""

import contextlib
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-kubewarden-audit-scanner.yml"
MODULE = "github.com/kubewarden/audit-scanner"
BASELINE = ("d634a49dc9570ccb0ec59cd0d0ea3d0fc9c02763", "f382260809e93bb60a1de7fd881d1f633f4942e7")
CANDIDATE = ("76a9ccb434613c3450f760e9d574b653c4ce9f4d", "20b70433f4ce03f96a9d01c7231108060305a4a3")


class KubewardenAuditScannerWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kubewarden-audit-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-kubewarden-audit-scanner"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.identity = re.search(r"^python3 - <<'PY'\n(.*?)^PY$",
                                  self.job["env"]["AUDIT_SCANNER_IDENTITY_COMMAND"], re.M | re.S)[1]
        self.output = self.root / "output"
        self.binary = self.root / "audit-scanner"
        self.binary.write_bytes(b"unit binary fixture, not native evidence")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.values = {
            "steps.metadata.outputs.current_version": "v1.24.0",
            "steps.metadata.outputs.latest_version": "v1.25.0",
            "steps.version.outputs.version": "1.24.0",
            "steps.version.outputs.identity_reported_version": "(devel)",
            "steps.install.outputs.binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            "steps.version.outcome": "success",
        }
        for i in range(1, 7):
            self.values[f"steps.test{i}.outputs.status"] = "passed"
            self.values[f"steps.test{i}.outcome"] = "success"

    def fixture(self, tag="v1.24.0", reported="(devel)"):
        tag_object, commit = BASELINE if tag == "v1.24.0" else CANDIDATE
        self.git = {
            ("remote", "get-url", "origin"): "https://github.com/kubewarden/audit-scanner.git",
            ("rev-parse", "HEAD"): commit,
            ("rev-parse", "refs/tags/" + tag): tag_object,
            ("rev-parse", "refs/tags/" + tag + "^{commit}"): commit,
            ("describe", "--tags", "--exact-match", "HEAD"): tag,
            ("status", "--porcelain", "--untracked-files=all"): "",
            ("show", "-s", "--format=%ct", "HEAD"): "1743465600",
        }
        self.remote = f"{tag_object}\trefs/tags/{tag}\n{commit}\trefs/tags/{tag}^{{}}\n"
        self.metadata = (f"{self.binary}: go1.23.0\n\tpath\t{MODULE}\n\tmod\t{MODULE}\t{reported}\t\n"
                         f"\tbuild\tGOOS=linux\n\tbuild\tGOARCH=arm64\n\tbuild\tvcs=git\n"
                         f"\tbuild\tvcs.revision={commit}\n\tbuild\tvcs.time=2025-04-01T00:00:00Z\n"
                         "\tbuild\tvcs.modified=false\n")

    def execute_identity(self, tag="v1.24.0", source_only=False):
        self.output.write_text("")
        stdout, stderr = io.StringIO(), io.StringIO()

        def check_output(args, **_kwargs):
            if args[:3] == ("git", "-C", str(self.root / "source")):
                return self.git[args[3:]]
            if args[:2] == ("git", "-c"):
                self.assertEqual(("git", "-c", "http.sslVerify=true", "-c", "http.followRedirects=false",
                                  "ls-remote", "--exit-code", "https://github.com/kubewarden/audit-scanner.git",
                                  "refs/tags/" + tag, "refs/tags/" + tag + "^{}"), args)
                return self.remote
            self.assertEqual(("go", "version", "-m", str(self.binary)), args)
            return self.metadata

        with patch.dict(os.environ, AUDIT_SOURCE_DIR=str(self.root / "source"), AUDIT_TAG=tag,
                        AUDIT_BINARY="" if source_only else str(self.binary), GITHUB_OUTPUT=str(self.output)), \
                patch("subprocess.check_output", side_effect=check_output), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compile(self.identity, "workflow-identity", "exec"), {})
        return stdout.getvalue(), stderr.getvalue(), self.fields()

    def fields(self):
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def stub(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def run_step(self, name, **environment):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else self.values.get(term, term if term.isdigit() else "")
                if value:
                    return value
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[name]["run"])
        self.output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
                                env={**os.environ, **self.job["env"], "GITHUB_OUTPUT": str(self.output),
                                     "RUNNER_TEMP": str(self.root), "AUDIT_BASELINE_DIR": str(self.root),
                                     "PATH": str(self.bin) + os.pathsep + os.environ["PATH"], **environment},
                                capture_output=True, text=True, timeout=10)
        return result, self.fields()

    def candidate_stubs(self):
        self.stub("sudo", 'exit "${INSTALL_EXIT:-0}"\n')
        self.stub("git", 'mkdir -p "${!#}"\nexit "${CLONE_EXIT:-0}"\n')
        self.stub("go", 'exit "${BUILD_EXIT:-0}"\n')
        return 'if [ -n "${AUDIT_BINARY:-}" ]; then echo "${CANDIDATE_VERSION:-1.25.0}"; exit "${IDENTITY_EXIT:-0}"; fi'

    def test_devel_requires_verified_source_and_binary_and_is_described_honestly(self):
        self.fixture()
        version, log, fields = self.execute_identity()
        self.assertEqual("1.24.0\n", version)
        self.assertEqual("(devel)", fields["identity_reported_version"])
        self.assertIn("official source tag and clean binary VCS; module reports (devel)", fields["identity_basis"])
        self.assertEqual(BASELINE[1], fields["identity_source_commit"])
        self.assertEqual(hashlib.sha256(self.binary.read_bytes()).hexdigest(), fields["identity_binary_sha256"])
        self.assertIn('"reported_version": "(devel)"', log)

    def test_stamped_baseline_and_candidate_report_exact_release(self):
        for tag in ("v1.24.0", "v1.25.0"):
            with self.subTest(tag=tag):
                self.fixture(tag, tag)
                version, _, fields = self.execute_identity(tag)
                self.assertEqual(tag[1:] + "\n", version)
                self.assertEqual(tag, fields["identity_reported_version"])

    def test_upstream_dependency_replacement_does_not_replace_main_module_identity(self):
        self.fixture()
        self.metadata += ("\tdep\tsigs.k8s.io/wg-policy-prototypes\tv0.0.0-20230505033312-51c21979086a\n"
                          "\t=>\tsigs.k8s.io/wg-policy-prototypes\tv0.0.0-20230505033312-51c21979086a\th1:fixture\n")
        version, _, fields = self.execute_identity()
        self.assertEqual("1.24.0\n", version)
        self.assertEqual("(devel)", fields["identity_reported_version"])

    def test_source_only_validation_cannot_emit_installed_version(self):
        self.fixture()
        with self.assertRaises(SystemExit) as raised:
            self.execute_identity(source_only=True)
        self.assertEqual(0, raised.exception.code)
        self.assertEqual({}, self.fields())

    def test_failed_identity_commands_cannot_emit_version(self):
        self.fixture()
        for failure in (subprocess.CalledProcessError(128, "git"), FileNotFoundError("go")):
            with self.subTest(failure=failure), patch("subprocess.check_output", side_effect=failure), \
                    patch.dict(os.environ, AUDIT_SOURCE_DIR=str(self.root), AUDIT_TAG="v1.24.0",
                               AUDIT_BINARY=str(self.binary), GITHUB_OUTPUT=str(self.output)):
                self.output.write_text("")
                with self.assertRaises(type(failure)):
                    exec(compile(self.identity, "workflow-identity", "exec"), {})
                self.assertEqual({}, self.fields())

    def test_wrong_source_repo_revision_tag_and_dirty_checkout_fail(self):
        self.fixture()
        changes = [(key, "wrong") for key in self.git if key[0] != "show"]
        for key, value in changes:
            with self.subTest(key=key):
                self.fixture()
                self.git[key] = value
                with self.assertRaises(SystemExit):
                    self.execute_identity()
                self.assertEqual({}, self.fields())

    def test_official_tag_must_match_both_pinned_object_and_peeled_commit(self):
        for remote in ("", "not a ref", "0" * 40 + "\trefs/tags/v1.24.0\n",
                       BASELINE[0] + "\trefs/tags/v1.24.0\n" + "0" * 40 + "\trefs/tags/v1.24.0^{}\n"):
            with self.subTest(remote=remote):
                self.fixture()
                self.remote = remote
                with self.assertRaises(SystemExit):
                    self.execute_identity()
                self.assertEqual({}, self.fields())
        self.fixture()
        with self.assertRaisesRegex(SystemExit, "Unreviewed"):
            self.execute_identity("v1.24.1")

    def test_missing_conflicting_or_wrong_binary_identity_fails(self):
        mutations = [
            (MODULE, "example.invalid/audit-scanner"),
            ("\tpath\t" + MODULE, "\tpath\t" + MODULE + "/other"),
            (BASELINE[1], CANDIDATE[1]), ("vcs.modified=false", "vcs.modified=true"),
            ("vcs=git", "vcs=hg"), ("GOARCH=arm64", "GOARCH=amd64"), ("GOOS=linux", "GOOS=darwin"),
            ("2025-04-01T00:00:00Z", "2025-04-02T00:00:00Z"),
            ("\tbuild\tvcs.modified=false\n", ""), ("\tbuild\tvcs.revision=" + BASELINE[1] + "\n", ""),
            ("\tmod\t", "\tdep\t"),
            ("vcs.modified=false", "vcs.modified=false\n\tbuild\tvcs.modified=false"),
        ]
        for old, new in mutations:
            with self.subTest(old=old, new=new):
                self.fixture()
                self.metadata = self.metadata.replace(old, new)
                with self.assertRaises(SystemExit):
                    self.execute_identity()
                self.assertEqual({}, self.fields())
        for extra in (f"\tmod\t{MODULE}\t(devel)\n", f"\t=>\t{MODULE}\tv1.24.0\n"):
            self.fixture()
            self.metadata += extra
            with self.assertRaises(SystemExit):
                self.execute_identity()

    def test_wrong_release_versions_and_candidate_devel_fail(self):
        for tag, versions in (("v1.24.0", ("", "1.24.0", "v1.25.0", "v1.24.0+dirty", "v1.24.0-rc1", "v1.24.0.1")),
                              ("v1.25.0", ("(devel)", "v1.24.0", "v1.25.0+dirty", "v1.25.0-rc1"))):
            for reported in versions:
                with self.subTest(tag=tag, reported=reported):
                    self.fixture(tag, reported)
                    with self.assertRaises(SystemExit):
                        self.execute_identity(tag)
                    self.assertEqual({}, self.fields())

    def test_version_step_and_test2_require_actual_identity_and_original_binary_hash(self):
        self.stub("sha256sum", f'echo "${{HASH:-{self.values["steps.install.outputs.binary_sha256"]}}}  binary"\n')
        for step in ("version", "test2"):
            for command, extra, passed in (("echo 1.24.0", {}, True), ("exit 37", {}, False),
                                           ("echo 1.24.0", {"HASH": "wrong"}, False)):
                with self.subTest(step=step, command=command, extra=extra):
                    result, fields = self.run_step(step, AUDIT_SCANNER_IDENTITY_COMMAND=command, **extra)
                    self.assertEqual(passed, result.returncode == 0, result.stderr)
                    if step == "test2":
                        self.assertEqual("passed" if passed else "failed", fields["status"])
                        self.assertIn("duration", fields)
                    elif not passed:
                        self.assertNotIn("version", fields)
        for version in ("(devel)", "1.25.0", "", "1.24.0-rc1"):
            result, fields = self.run_step("test2", AUDIT_SCANNER_IDENTITY_COMMAND=f"echo '{version}'")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", fields["status"])

    def test_candidate_success_is_cli_scope_and_cleans_its_directory(self):
        result, fields = self.run_step("test6", AUDIT_SCANNER_IDENTITY_COMMAND=self.candidate_stubs())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", fields["status"])
        self.assertEqual("1.25.0", fields["next_installed_version"])
        self.assertIn("module reports (devel)", fields["comparison"])
        self.assertIn("No Kubernetes cluster scan", fields["comparison"])
        self.assertEqual([], list(self.root.glob("audit-scanner-next.*")))

    def test_candidate_failures_cannot_emit_pass_or_leak_owned_directory(self):
        helper = self.candidate_stubs()
        for environment in ({"INSTALL_EXIT": "31"}, {"CLONE_EXIT": "32"}, {"BUILD_EXIT": "33"},
                            {"IDENTITY_EXIT": "34"}, {"CANDIDATE_VERSION": "1.24.0"}):
            with self.subTest(environment=environment):
                result, fields = self.run_step("test6", AUDIT_SCANNER_IDENTITY_COMMAND=helper, **environment)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", fields["status"])
                self.assertNotEqual("next_install_validated", fields.get("decision"))
                self.assertIn("duration", fields)
                self.assertEqual([], list(self.root.glob("audit-scanner-next.*")))

    def test_late_failure_overrides_success_and_preserves_nonzero_exit(self):
        self.stub("sha256sum", f'echo "{self.values["steps.install.outputs.binary_sha256"]}  binary"\n')
        for step, helper in (("test2", "echo 1.24.0"), ("test6", self.candidate_stubs())):
            with self.subTest(step=step):
                self.steps[step]["run"] = self.steps[step]["run"].replace("finish 0", "exit 37")
                result, fields = self.run_step(step, AUDIT_SCANNER_IDENTITY_COMMAND=helper)
                self.assertEqual(37, result.returncode, result.stderr)
                self.assertEqual("failed", fields["status"])
                self.assertIn("duration", fields)

    def test_any_failed_or_missing_baseline_blocks_candidate_success_claim(self):
        for i in range(1, 6):
            for field, bad in (("outputs.status", "failed"), ("outputs.status", ""), ("outcome", "failure")):
                with self.subTest(step=i, field=field, bad=bad):
                    key = f"steps.test{i}.{field}"
                    previous = self.values[key]
                    self.values[key] = bad
                    result, fields = self.run_step("test6")
                    self.values[key] = previous
                    self.assertEqual(0, result.returncode)
                    self.assertEqual("skipped", fields["status"])
                    self.assertEqual("baseline_failed", fields["decision"])
                    self.assertNotIn("next_installed_version", fields)
                    self.assertNotIn("passed smoke", fields.get("comparison", ""))

    def test_summary_and_badge_require_all_six_successful_outcomes(self):
        result, fields = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("success", fields["overall_status"])
        self.assertEqual("passing", fields["badge_status"])
        self.assertEqual("6", fields["passed"])
        for i in range(1, 7):
            for field, bad in (("outputs.status", "failed"), ("outputs.status", ""), ("outcome", "failure")):
                with self.subTest(step=i, field=field, bad=bad):
                    key = f"steps.test{i}.{field}"
                    previous = self.values[key]
                    self.values[key] = bad
                    result, fields = self.run_step("summary")
                    self.values[key] = previous
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failure", fields["overall_status"])
                    self.assertEqual("1", fields["failed"])
                    self.assertEqual("failing", fields["badge_status"])
                    self.assertEqual("0" if i == 6 else "1", fields["core_failed"])

    def test_baseline_failure_counts_unattempted_candidate_as_skipped_without_passing(self):
        self.values.update({"steps.test2.outputs.status": "failed", "steps.test2.outcome": "failure",
                            "steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": "baseline_failed"})
        result, fields = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failure", fields["overall_status"])
        self.assertEqual("failing", fields["badge_status"])
        self.assertEqual(("4", "1", "1", "1"), tuple(fields[k] for k in ("passed", "failed", "skipped", "core_failed")))

    def assert_incomplete_baseline_skip_is_failure(self):
        self.values.update({"steps.test2.outputs.status": "failed", "steps.test2.outcome": "failure",
                            "steps.test6.outputs.status": "skipped", "steps.test6.outputs.decision": "baseline_failed"})
        result, fields = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failure", fields["overall_status"])
        self.assertEqual("failing", fields["badge_status"])
        self.assertEqual(("4", "2", "0", "1"), tuple(fields[k] for k in ("passed", "failed", "skipped", "core_failed")))

    def test_baseline_skip_with_failed_candidate_outcome_counts_as_failure(self):
        self.values["steps.test6.outcome"] = "failure"
        self.assert_incomplete_baseline_skip_is_failure()

    def test_baseline_skip_with_missing_candidate_outcome_counts_as_failure(self):
        self.values.pop("steps.test6.outcome")
        self.assert_incomplete_baseline_skip_is_failure()

    def test_builds_preserve_vcs_and_do_not_inject_release_versions(self):
        for step in ("install", "test6"):
            body = self.steps[step]["run"]
            self.assertIn("go build -buildvcs=true -mod=readonly", body)
            self.assertNotIn("-ldflags", body)
            self.assertIn("https://github.com/kubewarden/audit-scanner.git", body)
            self.assertLess(body.index('bash -euo pipefail -c "$AUDIT_SCANNER_IDENTITY_COMMAND"'), body.index("go build"))
        self.assertIn("audit-scanner scan --help", self.steps["test5"]["run"])


if __name__ == "__main__":
    unittest.main()
