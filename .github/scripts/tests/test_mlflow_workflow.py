"""MLflow exact source/runtime identity, real health contracts and fail-closed summaries."""

import contextlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml


ROOT = Path(__file__).resolve().parents[3]


class MlflowWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mlflow-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.job = yaml.safe_load((ROOT / ".github/workflows/test-mlflow.yml").read_text())["jobs"]["test-mlflow"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.runtime = re.search(r"^python - <<'PY'\n(.*?)^PY$", self.job["env"]["MLFLOW_SMOKE_COMMAND"], re.M | re.S)[1]

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
                                env={**os.environ, **self.job["env"], "GITHUB_OUTPUT": str(output), **environment},
                                capture_output=True, text=True, timeout=10)
        return result, dict(line.split("=", 1) for line in output.read_text().splitlines())

    def statuses(self):
        return {f"steps.test{i}.{key}": value for i in range(1, 7)
                for key, value in (("outputs.status", "passed"), ("outcome", "success"))}

    def execute_runtime(self, expected="2.4.0", installed=None, cli=None, body=b"OK", exited=None, tables=("experiments", "runs")):
        directory = self.root / "runtime"
        directory.mkdir(exist_ok=True)
        for filename in ("tracking.db", "runtime-proof.json"):
            (directory / filename).unlink(missing_ok=True)
        module = SimpleNamespace(__version__=installed or expected, __file__=str(directory / "venv/lib/mlflow/__init__.py"))
        self.process = Mock(pid=12345678)
        self.process.poll.return_value = exited
        self.process.returncode = exited
        self.process.wait.return_value = 0
        def popen(command, **kwargs):
            self.command = command
            kwargs["stdout"].write("server diagnostic fixture\n")
            kwargs["stdout"].flush()
            with contextlib.closing(sqlite3.connect(directory / "tracking.db")) as connection:
                for table in tables:
                    connection.execute(f"CREATE TABLE {table} (id INTEGER)")
                connection.commit()
            return self.process
        response = io.BytesIO(body)
        response.status = 200
        self.printed = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, WORKDIR=str(directory), SMOKE_VERSION=expected))
            stack.enter_context(patch.dict("sys.modules", mlflow=module))
            stack.enter_context(patch("importlib.metadata.version", return_value=installed or expected))
            stack.enter_context(patch("subprocess.check_output", return_value=f"mlflow, version {cli or expected}\n"))
            stack.enter_context(patch("subprocess.Popen", side_effect=popen))
            sockets = stack.enter_context(patch("socket.socket"))
            sockets.return_value.__enter__.return_value.getsockname.return_value = ("127.0.0.1", 54321)
            stack.enter_context(patch("urllib.request.urlopen", return_value=response))
            stack.enter_context(patch("time.sleep"))
            self.kill = stack.enter_context(patch("os.killpg"))
            stack.enter_context(contextlib.redirect_stdout(self.printed))
            exec(compile(self.runtime, "mlflow-runtime", "exec"), {})
        return json.loads((directory / "runtime-proof.json").read_text())

    def test_source_uses_exact_version_field_and_tag(self):
        source = self.root / "baseline-src/mlflow"
        source.mkdir(parents=True)
        binary = self.root / "bin"
        binary.mkdir()
        git = binary / "git"
        git.write_text('#!/bin/sh\ncase "$*" in *refs/tags/*) echo "$TAG_COMMIT" ;; *) echo source-a ;; esac\n')
        git.chmod(0o755)
        for declaration, tag, commit, valid in (
            ('VERSION = "2.4.0"', "v2.4.0", "source-a", True),
            ('VERSION = "2.5.0"', "v2.4.0", "source-a", False),
            ('__version__ = "2.4.0"', "v2.4.0", "source-a", False),
            ('VERSION = "2.4.0"', "default_branch", "source-a", False),
            ('VERSION = "2.4.0"', "v2.4.0", "source-b", False),
        ):
            with self.subTest(declaration=declaration, tag=tag, commit=commit):
                (source / "version.py").write_text(declaration + "\n")
                result, output = self.run_step("test2", {"steps.install.outputs.install_mode": "github_source",
                    "steps.install.outputs.resolved_tag": tag}, PATH=str(binary) + os.pathsep + os.environ["PATH"], TAG_COMMIT=commit)
                self.assertEqual(valid, result.returncode == 0, result.stderr)
                self.assertEqual("passed" if valid else "failed", output["status"])

    def test_real_health_contract_checks_version_and_sqlite(self):
        for version in ("2.4.0", "3.10.0"):
            proof = self.execute_runtime(expected=version)
            self.assertEqual(version, proof["version"])
            self.assertEqual("OK", proof["health_body"])
            self.assertEqual(["experiments", "runs"], proof["tables"])
            self.assertIn("sqlite:///", " ".join(proof["command"]))
            self.kill.assert_called_once()
            self.process.wait.assert_called_once()

    def test_wrong_installed_or_cli_version_cannot_pass(self):
        for expected in ("2.4.0", "3.10.0"):
            for mismatch in ({"installed": "99.0.0"}, {"cli": "99.0.0"}):
                with self.subTest(expected=expected, mismatch=mismatch), self.assertRaises(AssertionError):
                    self.execute_runtime(expected=expected, **mismatch)

    def test_bad_health_early_exit_and_missing_backend_fail_with_cleanup(self):
        for arguments in ({"body": b"nonempty error"}, {"exited": 7}, {"tables": ("experiments",)}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(AssertionError):
                    self.execute_runtime(**arguments)
                self.kill.assert_called_once()
                self.process.wait.assert_called_once()
                self.assertIn("server diagnostic fixture", self.printed.getvalue())
                self.assertFalse((self.root / "runtime/runtime-proof.json").exists())

    def test_failed_runtime_and_wrong_candidate_tag_cannot_pass(self):
        result, output = self.run_step("test5", MLFLOW_SMOKE_COMMAND="exit 31")
        self.assertEqual(31, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertIn("duration", output)
        self.steps["probe"] = {"run": "set -euo pipefail\n" + self.steps["test6"]["with"]["limited_cpu_probe"]}
        for version, tag in (("2.4.0", "v2.4.0"), ("3.10.0", "v2.4.0")):
            result, _ = self.run_step("probe", LATEST_VERSION=version, CANDIDATE_TAG=tag, MLFLOW_SMOKE_COMMAND="exit 0")
            self.assertNotEqual(0, result.returncode)

    def test_summary_rejects_outputs_with_failed_or_missing_outcomes(self):
        for number in range(1, 7):
            for status, outcome in (("passed", "failure"), ("passed", "cancelled"), ("passed", ""), ("", "success"), ("skipped", "success")):
                values = self.statuses()
                values.update({f"steps.test{number}.outputs.status": status, f"steps.test{number}.outcome": outcome})
                result, output = self.run_step("summary", values)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("1", output["failed"])
                self.assertEqual("1" if number <= 5 else "0", output["core_failed"])

    def test_only_proven_candidate_skip_is_allowed(self):
        result, output = self.run_step("summary", self.statuses())
        self.assertEqual((0, "6"), (result.returncode, output["passed"]))
        for decision, outcome, valid in (("no_newer_stable_available", "success", True),
                ("no_newer_stable_available", "cancelled", False), ("no_newer_stable_available", "failure", False),
                ("limited_cpu_smoke_deferred", "success", False)):
            values = self.statuses()
            values.update({"steps.test6.outputs.status": "skipped", "steps.test6.outcome": outcome,
                           "steps.test6.outputs.decision": decision})
            result, output = self.run_step("summary", values)
            self.assertEqual(valid, result.returncode == 0)
            self.assertEqual("1" if valid else "0", output["skipped"])

    def test_named_outputs_and_existing_runtime_scope_are_retained(self):
        command = self.job["env"]["MLFLOW_SMOKE_COMMAND"]
        self.assertNotIn("install --upgrade pip setuptools", command)
        self.assertIn('"mlflow==$SMOKE_VERSION"', command)
        self.assertEqual("false", self.steps["test6"]["with"]["defer_on_limited_cpu_probe_failure"])
        for number in range(1, 6):
            self.assertIn('echo "status=failed" >> "$GITHUB_OUTPUT"', self.steps[f"test{number}"]["run"])
            self.assertIn('echo "duration=0" >> "$GITHUB_OUTPUT"', self.steps[f"test{number}"]["run"])


if __name__ == "__main__":
    unittest.main()
