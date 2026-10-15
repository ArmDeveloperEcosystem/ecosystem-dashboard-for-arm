"""Azure CLI source-wheel, exact-runtime and outcome accounting regressions."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[3]


class AzureCliWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="azurecli-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load((ROOT / ".github/workflows/test-azurecli.yml").read_text())["jobs"]["test-azurecli"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.blocks = re.findall(r"^[ \t]*python - <<'PY'\n(.*?)^PY$", self.job["env"]["AZURE_SMOKE_COMMAND"], re.M | re.S)

    def run_step(self, name, values=None, **environment):
        values = values or {}
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term.strip("'")
                if values.get(term):
                    return values[term]
            return ""
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[name]["run"])
        output = self.root / "output"
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=self.root,
                                env={**os.environ, **self.job["env"], "GITHUB_OUTPUT": str(output),
                                     **getattr(self, "runtime_env", {}), **environment},
                                capture_output=True, text=True, timeout=10)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def statuses(self):
        return {f"steps.test{i}.{key}": value for i in range(1, 7)
                for key, value in (("outputs.status", "passed"), ("outcome", "success"))}

    def execute(self, block, version="2.46.0"):
        with patch.dict(os.environ, WORKDIR=str(self.root), SMOKE_VERSION=version), contextlib.redirect_stdout(io.StringIO()):
            exec(compile(self.blocks[block], "azure-runtime", "exec"), {})

    def test_exact_official_source_digest_is_required(self):
        data = b"source fixture"
        for version, host, digest, valid in (
            ("4.9.3", "files.pythonhosted.org", hashlib.sha256(data).hexdigest(), True),
            ("4.13.2", "files.pythonhosted.org", hashlib.sha256(data).hexdigest(), False),
            ("4.9.3", "example.invalid", hashlib.sha256(data).hexdigest(), False),
            ("4.9.3", "files.pythonhosted.org", "bad-digest", False),
        ):
            with self.subTest(version=version, host=host, digest=digest):
                metadata = {"info": {"version": version}, "urls": [{"packagetype": "sdist",
                            "url": f"https://{host}/source.tar.gz", "digests": {"sha256": digest}}]}
                with patch("urllib.request.urlopen", side_effect=[io.BytesIO(json.dumps(metadata).encode()), io.BytesIO(data)]):
                    if valid:
                        self.execute(0)
                        self.assertEqual(data, (self.root / "antlr4-4.9.3.tar.gz").read_bytes())
                    else:
                        with self.assertRaises(AssertionError):
                            self.execute(0)

    def test_built_wheel_must_be_exact_antlr_distribution(self):
        directory = self.root / "wheels"
        directory.mkdir()
        for name, version in (("antlr4-python3-runtime", "4.9.3"), ("antlr4-python3-runtime", "4.13.2"), ("unrelated", "4.9.3")):
            with self.subTest(name=name, version=version):
                with zipfile.ZipFile(directory / "fixture.whl", "w") as wheel:
                    wheel.writestr("fixture.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n")
                if (name, version) == ("antlr4-python3-runtime", "4.9.3"):
                    self.execute(1)
                else:
                    with self.assertRaises(AssertionError):
                        self.execute(1)

    def test_installed_and_cli_versions_must_match_baseline_or_candidate(self):
        for expected in ("2.46.0", "2.84.0"):
            for installed, cli, antlr in ((expected, expected, "4.9.3"), (expected, expected + " *", "4.9.3"),
                                          ("99.0.0", expected, "4.9.3"), (expected, "99.0.0 *", "4.9.3"),
                                          (expected, expected + " unexpected", "4.9.3"),
                                          (expected, "99.0.0", "4.9.3"), (expected, expected, "4.13.2")):
                with self.subTest(expected=expected, installed=installed, cli=cli, antlr=antlr):
                    (self.root / "az-version.txt").write_text(f"azure-cli                         {cli}\n")
                    valid = installed == expected and cli in (expected, expected + " *") and (expected != "2.46.0" or antlr == "4.9.3")
                    with patch("importlib.metadata.version", side_effect=lambda name: installed if name == "azure-cli" else antlr):
                        if valid:
                            self.execute(2, expected)
                        else:
                            with self.assertRaises(AssertionError):
                                self.execute(2, expected)

    def test_runtime_failures_cannot_emit_pass(self):
        for command, passed in (("exit 31", False), ('test "$SMOKE_VERSION" = 2.46.0; test "$SMOKE_HELP" = account', True)):
            result, output = self.run_step("test5", AZURE_SMOKE_COMMAND=command)
            self.assertEqual(passed, result.returncode == 0, result.stderr)
            self.assertEqual("passed" if passed else "failed", output["status"])
            self.assertIn("duration", output)

    def test_candidate_never_retests_baseline_or_wrong_tag(self):
        self.steps["probe"] = {"run": "set -euo pipefail\n" + self.steps["test6"]["with"]["limited_cpu_probe"]}
        for version, tag in (("2.46.0", "azure-cli-2.46.0"), ("2.84.0", "azure-cli-2.46.0")):
            result, _ = self.run_step("probe", LATEST_VERSION=version, CANDIDATE_TAG=tag, AZURE_SMOKE_COMMAND="exit 0")
            self.assertNotEqual(0, result.returncode)

    def test_summary_requires_actual_outcome_for_every_pass(self):
        for number in range(1, 7):
            for status, outcome in (("passed", "failure"), ("passed", "cancelled"), ("passed", ""), ("", "success"), ("failed", "success")):
                with self.subTest(number=number, status=status, outcome=outcome):
                    values = self.statuses()
                    values.update({f"steps.test{number}.outputs.status": status, f"steps.test{number}.outcome": outcome})
                    result, output = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("1", output["failed"])
                    self.assertEqual("1" if number <= 5 else "0", output["core_failed"])

    def test_only_proven_candidate_skip_is_allowed(self):
        result, output = self.run_step("summary", self.statuses())
        self.assertEqual(0, result.returncode)
        self.assertEqual("6", output["passed"])
        for number, outcome, decision, valid in ((6, "success", "no_newer_stable_available", True),
                (6, "cancelled", "no_newer_stable_available", False), (6, "failure", "no_newer_stable_available", False),
                (6, "success", "limited_cpu_smoke_deferred", False), (2, "success", "no_newer_stable_available", False)):
            values = self.statuses()
            values.update({f"steps.test{number}.outputs.status": "skipped", f"steps.test{number}.outcome": outcome,
                           "steps.test6.outputs.decision": decision})
            result, output = self.run_step("summary", values)
            self.assertEqual(valid, result.returncode == 0)
            self.assertEqual("1" if valid else "0", output["skipped"])

    def test_contract_keeps_real_commands_and_named_outputs(self):
        command = self.job["env"]["AZURE_SMOKE_COMMAND"]
        for expected in ('az --version', 'az "$SMOKE_HELP" --help', '--only-binary=:all:', 'antlr4-python3-runtime/4.9.3/json', "'psutil~=5.9'"):
            self.assertIn(expected, command)
        self.assertEqual("false", self.steps["test6"]["with"]["defer_on_limited_cpu_probe_failure"])
        for number in range(1, 6):
            self.assertIn('echo "status=failed" >> "$GITHUB_OUTPUT"', self.steps[f"test{number}"]["run"])
            self.assertIn('echo "duration=0" >> "$GITHUB_OUTPUT"', self.steps[f"test{number}"]["run"])

    def prepare_runtime_stubs(self):
        """Execute the complete workflow shell, substituting only external tools/packages."""
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        home = self.root / "home"
        home.mkdir()
        self.runtime_env = {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                            "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1",
                            "TOOL_CALLS": str(self.root / "tool-calls")}

        def stub(name, body, interpreter="/bin/bash"):
            path = bin_dir / name
            path.write_text(f"#!{interpreter}\n" + textwrap.dedent(body))
            path.chmod(0o755)

        stub("uname", "echo aarch64\n")
        stub("timeout", 'shift\nexec "$@"\n')
        stub("git", """
            set -euo pipefail
            if [ "$1" = clone ]; then
              mkdir -p next-src
              touch next-src/README.md
            elif [ "$1" = -C ] && [ "$3" = rev-parse ]; then
              echo fixture-source-commit
            else
              exit 97
            fi
        """)
        stub("python", """
            import json
            import os
            from pathlib import Path
            import sys
            import types
            from unittest.mock import patch

            args = sys.argv[1:]
            with open(os.environ["TOOL_CALLS"], "a") as log:
                log.write(json.dumps(args) + "\\n")
            if args[:2] == ["-m", "venv"]:
                target = Path(args[2]) / "bin"
                target.mkdir(parents=True)
                (target / "activate").write_text("# fixture venv\\n")
            elif args[:2] == ["-m", "pip"]:
                if args[2] == os.environ.get("FAIL_PIP"):
                    sys.exit(23)
            elif args == ["-"]:
                source = sys.stdin.read()
                # Source download and wheel verification have separate tests above.
                if "urllib.request" in source or "zipfile" in source:
                    sys.exit(0)
                for name in ("azure", "azure.mgmt", "azure.mgmt.rdbms",
                             "azure.mgmt.rdbms.mysql_flexibleservers",
                             "azure.mgmt.rdbms.postgresql_flexibleservers"):
                    if name == os.environ.get("MISSING_IMPORT"):
                        continue
                    module = types.ModuleType(name)
                    module.__path__ = []
                    sys.modules[name] = module
                versions = {"azure-cli": os.environ["SMOKE_VERSION"],
                            "antlr4-python3-runtime": "4.9.3",
                            "azure-mgmt-rdbms": os.environ.get("RDBMS_VERSION", "10.2.0b6")}
                with patch("importlib.metadata.version", side_effect=versions.__getitem__):
                    exec(compile(source, "workflow-runtime", "exec"), {})
            else:
                sys.exit(98)
        """, interpreter=sys.executable)
        stub("az", """
            set -euo pipefail
            printf '%s\\n' "$*" >> "$HOME/az-calls"
            if [ "${FAIL_COMMAND:-}" = "$1" ] && [ "${FAIL_MODE:-}" = missing-help ]; then
              echo 'Unrelated help'
            elif [ "$1" = --version ]; then
              echo "azure-cli                         $SMOKE_VERSION *"
            else
              echo "Group: az $*"
            fi
            if [ "${FAIL_COMMAND:-}" = "$1" ]; then
              case "${FAIL_MODE:-module-error}" in
                module-error)
                  echo "ERROR: Error loading command module 'rdbms': No module named 'azure.mgmt.rdbms.mysql_flexibleservers'" >&2 ;;
                stdout-error) echo "ERROR: Error loading command module 'other': broken dependency" ;;
                traceback) echo 'Traceback (most recent call last):' >&2 ;;
                exit) exit 23 ;;
                missing-help) ;;
                *) exit 99 ;;
              esac
            fi
            echo "WARNING: You have 3 update(s) available. Consider updating your CLI installation with 'az upgrade'" >&2
        """)

    def run_runtime_lane(self, lane, **environment):
        if lane == "baseline":
            return self.run_step("test5", **environment)
        action = yaml.safe_load((ROOT / ".github/actions/generic-source-regression-check/action.yml").read_text())
        inputs = {key: value.get("default", "") for key, value in action["inputs"].items()}
        inputs.update(self.steps["test6"]["with"])
        inputs.update(baseline_version=self.job["env"]["BASELINE_VERSION"],
                      github_repo=self.job["env"]["GITHUB_REPO"], lane_kind=self.job["env"]["LANE_KIND"])

        def render(value):
            return re.sub(r"\$\{\{\s*inputs\.(\w+)\s*\}\}", lambda match: inputs[match[1]], value)

        step = action["runs"]["steps"][0]
        self.steps["runtime-candidate"] = {"run": render(step["run"])}
        return self.run_step("runtime-candidate", **{key: render(value) for key, value in step["env"].items()},
                             **environment)

    def assert_runtime_accounting(self, lane, result, output, passed):
        self.assertEqual(passed or lane == "candidate", result.returncode == 0, result.stderr)
        self.assertEqual("passed" if passed else "failed", output["status"], result.stdout + result.stderr)
        if lane == "candidate":
            self.assertEqual("limited_cpu_smoke_validated" if passed else "limited_cpu_smoke_failed", output["decision"])
            self.assertEqual("2.84.0" if passed else "limited_cpu_probe_failed", output["next_installed_version"])
        values = self.statuses()
        number = 5 if lane == "baseline" else 6
        values[f"steps.test{number}.outputs.status"] = output["status"]
        values[f"steps.test{number}.outcome"] = "success" if result.returncode == 0 else "failure"
        summary, counts = self.run_step("summary", values)
        self.assertEqual(passed, summary.returncode == 0, summary.stderr)
        self.assertEqual("0" if passed else "1", counts["failed"])
        self.assertEqual("1" if not passed and lane == "baseline" else "0", counts["core_failed"])
        if not passed:
            self.assertNotIn("Validated Azure CLI version=", result.stdout)

    def test_actual_workflow_runtime_accepts_healthy_cli_with_update_warnings(self):
        self.prepare_runtime_stubs()
        for lane, help_command, version in (("baseline", "account", "2.46.0"), ("candidate", "group", "2.84.0")):
            with self.subTest(lane=lane):
                result, output = self.run_runtime_lane(lane)
                self.assert_runtime_accounting(lane, result, output, True)
                self.assertIn(f"Validated Azure CLI version={version}", result.stdout)
                self.assertIn("WARNING:", result.stdout)
                calls = (self.root / "home/az-calls").read_text().splitlines()
                self.assertEqual(["--version", f"{help_command} --help", "mysql flexible-server --help",
                                  "postgres flexible-server --help"], calls[-4:])
                pip_calls = [json.loads(line) for line in (self.root / "tool-calls").read_text().splitlines()]
                install = next(args for args in pip_calls if f"azure-cli=={version}" in args)
                self.assertEqual(lane == "baseline", "azure-mgmt-rdbms==10.2.0b6" in install)
                self.assertIn(["-m", "pip", "check"], pip_calls)

    def test_actual_workflow_rejects_zero_exit_module_errors_and_nonzero_cli(self):
        self.prepare_runtime_stubs()
        for lane, help_command in (("baseline", "account"), ("candidate", "group")):
            for command in ("--version", help_command, "mysql", "postgres"):
                for mode in ("module-error", "stdout-error", "traceback", "exit", "missing-help"):
                    with self.subTest(lane=lane, command=command, mode=mode):
                        result, output = self.run_runtime_lane(lane, FAIL_COMMAND=command, FAIL_MODE=mode)
                        self.assert_runtime_accounting(lane, result, output, False)
                        if mode == "module-error":
                            self.assertIn("No module named 'azure.mgmt.rdbms.mysql_flexibleservers'", result.stdout)
                        if mode in ("module-error", "stdout-error", "traceback"):
                            self.assertIn("Azure CLI runtime error", result.stderr)

    def test_actual_workflow_rejects_dependency_and_baseline_import_failures(self):
        self.prepare_runtime_stubs()
        for lane in ("baseline", "candidate"):
            cases = [{"FAIL_PIP": "install"}, {"FAIL_PIP": "check"}]
            if lane == "baseline":
                cases += [{"RDBMS_VERSION": "10.2.0b18"},
                          {"MISSING_IMPORT": "azure.mgmt.rdbms.mysql_flexibleservers"},
                          {"MISSING_IMPORT": "azure.mgmt.rdbms.postgresql_flexibleservers"}]
            for environment in cases:
                with self.subTest(lane=lane, environment=environment):
                    result, output = self.run_runtime_lane(lane, **environment)
                    self.assert_runtime_accounting(lane, result, output, False)

    def test_preserves_pinned_versions_and_regression_applicability(self):
        self.assertEqual("2.46.0", self.job["env"]["BASELINE_VERSION"])
        self.assertEqual("applicable", self.job["outputs"]["regression_policy"])
        candidate = self.steps["test6"]["with"]
        self.assertEqual("2.84.0", candidate["next_version_override"])
        self.assertEqual("azure-cli-2.84.0", candidate["candidate_tag_override"])
        self.assertEqual("false", candidate["defer_on_limited_cpu_probe_failure"])


if __name__ == "__main__":
    unittest.main()
