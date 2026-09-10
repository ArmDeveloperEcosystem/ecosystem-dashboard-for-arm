"""Fault tests for actual MAAS workflow shell; fixtures are not product evidence."""

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
import types
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as observation_audit
from package_result_policy import expected_regression_metadata, validate_six_test_result


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-maas.yml"


class MaasWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="maas-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-maas"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.values = {
            "github.run_id": "unit", "github.run_attempt": "1",
            "steps.install.outcome": "success",
            "steps.install.outputs.installation_method": "deb",
            "steps.version.outcome": "success",
            "steps.version.outputs.version": "3.6.5",
            "steps.version.outputs.installation_method": "deb",
            "steps.test6.outputs.decision": "not_applicable_package_manager",
            "steps.test6.outputs.installation_method": "deb",
        }
        for number in range(1, 7):
            self.values.update({f"steps.test{number}.outcome": "success",
                f"steps.test{number}.outputs.status": "skipped" if number == 6 else "passed",
                f"steps.test{number}.outputs.duration": "1"})
        self.env = {**self.job["env"], "GITHUB_OUTPUT": str(self.root / "output"),
                    "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "HOME": str(self.root), "TMPDIR": str(self.root), "LC_ALL": "C", "LANG": "C",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "DOCKER_RC": "0", "DOCKER_STDOUT": "", "TEST_ARCH": "aarch64"}
        self.tool("docker", 'printf "%s" "$DOCKER_STDOUT"\nexit "$DOCKER_RC"\n')
        self.tool("uname", 'printf "%s\\n" "$TEST_ARCH"\n')
        self.calls = 0

    def tool(self, name, script):
        target = self.bin / name
        target.write_text("#!/bin/bash\nset -eu\n" + script)
        target.chmod(0o755)

    def render(self, source):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if self.values.get(term):
                    return self.values[term]
            return ""
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)

    def run_step(self, step, **environment):
        source = self.steps[step]["run"]
        script = self.render(source)
        env = {key: self.render(str(value)) for key, value in self.env.items()}
        env.update(environment)
        output = Path(env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
            env=env, cwd=self.root, capture_output=True, text=True, timeout=15)
        lines = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(line) == 2 for line in lines), lines)
        outputs = dict(lines)
        self.assertEqual(len(lines), len(outputs), "Duplicate output keys")
        if evidence := os.environ.get("WORKFLOW_EVIDENCE_ROOT"):
            self.calls += 1
            directory = Path(evidence) / self._testMethodName / str(self.calls)
            directory.mkdir(parents=True)
            for name, text in {"source.sh": source, "rendered.sh": script,
                "env.json": json.dumps(env, indent=2),
                "values.json": json.dumps(self.values, indent=2),
                "stdout.txt": result.stdout, "stderr.txt": result.stderr,
                "github-output.txt": output.read_text(), "exit.txt": str(result.returncode),
                "workflow.sha256": hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()}.items():
                (directory / name).write_text(text)
        return result, outputs

    def test_every_shell_block_parses(self):
        for step in self.job["steps"]:
            if "run" in step:
                result = subprocess.run(["bash", "-n"], input=self.render(step["run"]),
                                        text=True, capture_output=True)
                self.assertEqual(0, result.returncode, step["name"] + result.stderr)

    def test_actual_auditor_sees_all_contract_outputs(self):
        for number in range(1, 7):
            for output in ("status", "duration"):
                self.assertTrue(observation_audit._step_emits_output(
                    WORKFLOW.parents[2], self.steps[f"test{number}"], output), (number, output))
        for output in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status"):
            self.assertTrue(observation_audit._step_emits_output(
                WORKFLOW.parents[2], self.steps["summary"], output), output)
        for output in ("version", "package_version", "installation_method"):
            self.assertTrue(observation_audit._step_emits_output(
                WORKFLOW.parents[2], self.steps["version"], output), output)
        pairs = set(observation_audit._step_literal_pairs(WORKFLOW.parents[2], self.steps["test6"]))
        self.assertEqual({("baseline_install_failed", "skipped"), ("baseline_failed", "skipped"),
                          ("not_applicable_package_manager", "skipped")}, pairs)
        for decision, status in pairs:
            self.assertEqual("not_applicable" if decision == "not_applicable_package_manager" else status, expected_regression_metadata(
                decision=decision, core_failed=0 if decision == "not_applicable_package_manager" else 1)["status"])

    def test_valid_summary_counts_five_core_and_real_pm_skip(self):
        result, regression = self.run_step("test6")
        self.assertEqual(0, result.returncode, result.stderr)
        self.values.update({f"steps.test6.outputs.{k}": v for k, v in regression.items()})
        self.values["steps.test6.outputs.duration"] = "1"
        result, outputs = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("5", "0", "1", "0", "6", "success", "passing"),
            tuple(outputs[k] for k in ("passed", "failed", "skipped", "core_failed", "duration", "overall_status", "badge_status")))
        self.assertEqual("success", self.validate_row(regression, outputs))

    def validate_row(self, regression, summary):
        details = [{"name": self.steps[f"test{i}"]["name"],
                    "status": self.values[f"steps.test{i}.outputs.status"]} for i in range(1, 6)]
        details.append({"name": self.steps["test6"]["name"], **regression})
        return validate_six_test_result(details=details, decision=regression["decision"],
            **{key: int(summary[key]) for key in ("passed", "failed", "skipped", "core_failed")})

    def test_real_shell_fault_rows_are_accepted_by_unchanged_policy(self):
        original = dict(self.values)
        for number in range(1, 6):
            with self.subTest(number=number):
                self.values = dict(original)
                result, outputs = self.run_step(f"test{number}", DOCKER_RC="37")
                self.assertNotEqual(0, result.returncode)
                self.values[f"steps.test{number}.outcome"] = "failure"
                self.values.update({f"steps.test{number}.outputs.{k}": v for k, v in outputs.items()})
                result, regression = self.run_step("test6")
                self.assertEqual(0, result.returncode)
                self.assertEqual("baseline_failed", regression["decision"])
                self.values.update({f"steps.test6.outputs.{k}": v for k, v in regression.items()})
                result, summary = self.run_step("summary")
                self.assertEqual(1, result.returncode)
                self.assertEqual(("4", "1", "1", "1", "failing"),
                    tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed", "badge_status")))
                self.assertEqual("failure", self.validate_row(regression, summary))
                self.values["steps.test6.outputs.decision"] = "baseline_install_failed"
                result, invalid = self.run_step("summary")
                self.assertEqual("0", invalid["skipped"])

    def test_install_failure_is_a_valid_failure_row_and_has_exact_reason(self):
        self.values["steps.install.outcome"] = "failure"
        for number in range(1, 6):
            self.values[f"steps.test{number}.outputs.status"] = "failed"
            self.values[f"steps.test{number}.outcome"] = "failure"
        result, regression = self.run_step("test6", DOCKER_RC="37")
        self.assertEqual(0, result.returncode)
        self.assertEqual("baseline_install_failed", regression["decision"])
        self.values.update({f"steps.test6.outputs.{k}": v for k, v in regression.items()})
        result, summary = self.run_step("summary")
        self.assertEqual(1, result.returncode)
        self.assertEqual(("0", "5", "1", "5"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))
        self.assertEqual("failure", self.validate_row(regression, summary))
        self.values["steps.test6.outputs.decision"] = "baseline_failed"
        result, invalid = self.run_step("summary")
        self.assertEqual("0", invalid["skipped"])

    def test_core_missing_status_outcome_or_duration_never_passes(self):
        for number in range(1, 6):
            for field, invalid in (("outcome", ("", "failure", "cancelled", "skipped")),
                                   ("outputs.status", ("", "failed", "skipped", "unknown")),
                                   ("outputs.duration", ("", "-1", "oops", "1+1", "999999999"))):
                key = f"steps.test{number}.{field}"
                original = self.values[key]
                for value in invalid:
                    with self.subTest(number=number, field=field, value=value):
                        self.values[key] = value
                        result, outputs = self.run_step("summary")
                        self.assertEqual(1, result.returncode, result.stderr)
                        self.assertEqual("1", outputs["core_failed"])
                        self.assertEqual("failing", outputs["badge_status"])
                        self.assertEqual("failure", outputs["overall_status"])
                self.values[key] = original

    def test_pm_skip_is_strict_about_decision_outcome_duration_and_evidence(self):
        for key, values in {
            "steps.test6.outputs.decision": ("", "baseline_failed", "baseline_install_failed", "not_configured"),
            "steps.test6.outcome": ("", "failure", "cancelled", "skipped"),
            "steps.test6.outputs.status": ("", "passed", "failed"),
            "steps.test6.outputs.duration": ("", "bad", "-1"),
            "steps.test6.outputs.installation_method": ("", "pip", "source"),
        }.items():
            original = self.values[key]
            for value in values:
                with self.subTest(key=key, value=value):
                    self.values[key] = value
                    result, outputs = self.run_step("summary")
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertEqual(("5", "1", "0", "0", "failure"),
                        tuple(outputs[k] for k in ("passed", "failed", "skipped", "core_failed", "overall_status")))
            self.values[key] = original

    def test_install_or_version_failure_invalidates_provenance(self):
        for key in ("steps.install.outcome", "steps.version.outcome",
                    "steps.install.outputs.installation_method", "steps.version.outputs.installation_method",
                    "steps.version.outputs.version"):
            original = self.values[key]
            self.values[key] = ""
            result, outputs = self.run_step("summary")
            self.assertEqual(1, result.returncode)
            self.assertEqual("5", outputs["core_failed"])
            self.values[key] = original

    def test_baseline_guards_skip_without_calling_package_manager(self):
        self.values["steps.install.outcome"] = "failure"
        result, outputs = self.run_step("test6", DOCKER_RC="97")
        self.assertEqual(0, result.returncode)
        self.assertEqual(("baseline_install_failed", "skipped"), (outputs["decision"], outputs["status"]))
        self.values["steps.install.outcome"] = "success"
        self.values["steps.test5.outcome"] = "failure"
        result, outputs = self.run_step("test6", DOCKER_RC="97")
        self.assertEqual(0, result.returncode)
        self.assertEqual(("baseline_failed", "skipped"), (outputs["decision"], outputs["status"]))
        self.values.update({f"steps.test6.outputs.{k}": v for k, v in outputs.items()})
        result, summary = self.run_step("summary")
        self.assertEqual(1, result.returncode)
        self.assertEqual(("4", "1", "1", "1"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))

    def test_failed_real_shell_commands_emit_failed_status_and_duration(self):
        for number in range(1, 6):
            for code in (1, 37, 127):
                with self.subTest(number=number, code=code):
                    result, outputs = self.run_step(f"test{number}", DOCKER_RC=str(code))
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failed", outputs["status"])
                    self.assertTrue(outputs["duration"].isdigit())
        result, outputs = self.run_step("version", DOCKER_RC="37", DOCKER_STDOUT="version=3.6.5\n")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("version", outputs)
        result, outputs = self.run_step("test6", DOCKER_RC="37")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("decision", outputs)
        self.assertTrue(outputs["duration"].isdigit())

    def test_region_help_and_native_host_assertions_reject_wrong_evidence(self):
        for help_text in ("", "python-libmaas --help", "Upgrades database schema for MAAS regiond."):
            result, outputs = self.run_step("test3", DOCKER_STDOUT=help_text)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", outputs["status"])
        result, outputs = self.run_step("test4", TEST_ARCH="x86_64")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])

    def identity(self, fault=None):
        """Run the actual identity helper with explicitly isolated unit fixtures."""
        version = types.SimpleNamespace(short_version="3.6.5", git_rev="474ecb517")
        maas = types.ModuleType("maasserver")
        maas.__file__ = "/usr/lib/python3/dist-packages/maasserver/__init__.py"
        maas.__version__ = "3.6.5"
        module = types.ModuleType("provisioningserver.utils.version")
        module.get_running_version = lambda: version
        if fault == "runtime": version.short_version = "0.6.8"
        if fault == "source": version.git_rev = "deadbeef0"
        if fault == "module": maas.__version__ = "0.6.8"
        if fault == "path": maas.__file__ = "/tmp/maasserver/__init__.py"
        def query(command, **kwargs):
            if fault == "command": raise subprocess.CalledProcessError(17, command)
            if command[1] == "-W":
                row = f'{command[-1]}\tinstall ok installed\t{self.job["env"]["MAAS_DEB_VERSION"]}\tall\tmaas\n'
                replacements = {"arch": ("\tall\t", "\tamd64\t"), "status": ("installed", "unpacked"),
                    "package": (command[-1], "python-libmaas"), "revision": (self.job["env"]["MAAS_DEB_VERSION"], "0.6.8"),
                    "source-package": ("\tmaas\n", "\tpython-libmaas\n")}
                if fault in replacements: row = row.replace(*replacements[fault])
                if fault == "duplicate": row += row
            else:
                owner = "maas-region-api" if command[-1] == "/usr/sbin/maas-region" else "python3-django-maas"
                row = f'{owner}: {command[-1]}\n'
                if fault == "owner": row = "other: " + command[-1] + "\n"
            return types.SimpleNamespace(stdout=row, stderr="diagnostic" if fault == "stderr" else "")
        with patch.dict(os.environ, self.job["env"]), patch.dict(sys.modules, {
                "maasserver": maas, "provisioningserver.utils.version": module}), \
             patch("subprocess.run", side_effect=query), patch.object(Path, "is_file", return_value=fault != "missing"), \
             patch("importlib.metadata.version", return_value="0.6.8" if fault == "distribution" else "3.6.5"), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            exec(compile(self.job["env"]["MAAS_IDENTITY"], "workflow:MAAS_IDENTITY", "exec"), {})
        return output.getvalue()

    def test_identity_helper_rejects_client_wrong_owner_version_arch_and_failed_queries(self):
        self.assertIn("version=3.6.5\n", self.identity())
        for fault in ("runtime", "source", "module", "path", "command", "arch", "status",
                      "package", "revision", "source-package", "duplicate", "owner", "stderr", "missing", "distribution"):
            with self.subTest(fault=fault), self.assertRaises((AssertionError, subprocess.CalledProcessError)):
                self.identity(fault)

    def api_assertions(self, fault=None):
        """Exercise the actual HTTP/SQL assertion code with labeled unit fixtures."""
        state = {}
        name = "maas-smoke-" + "a" * 32
        stage = "create"
        requests = types.ModuleType("requests")
        def request(method, url, **kwargs):
            nonlocal stage
            path = url.removeprefix("http://127.0.0.1:5240/MAAS/api/2.0/")
            status, data = 200, None
            if path == "version/":
                data = {"version": "None" if fault == "version" else "3.6.5", "capabilities": ["authenticate-api"]}
            elif method == "POST" and not kwargs["headers"]:
                status, data = (200 if fault == "unauthorized" else 401), "Forbidden"
            elif method == "POST":
                fields = {k: v[1] for k, v in kwargs["files"].items()}
                state[name] = fields
                data = dict(fields)
                if fault == "created-name": data["name"] = "other"
                if fault == "created-comment": data["comment"] = "other"
            elif method == "PUT":
                stage = "update"
                if fault != "stale-update": state[name]["comment"] = "persisted-update"
                data = dict(state[name])
            elif method == "DELETE":
                stage = "delete"
                del state[name]
                status, data = 204, ""
            elif method == "GET":
                status = 200 if name in state else 404
                data = dict(state[name]) if name in state else "No Tag matches the given query."
                if stage == "delete" and fault == "delete-status": status = 200
            else:
                raise AssertionError((method, path))
            response = types.SimpleNamespace(status_code=status, text=json.dumps(data),
                content=b"" if status == 204 else b"body", headers={"Content-Type": "application/json"})
            response.json = lambda: data
            return response
        requests.request = request
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, query, parameters):
                self.parameters = parameters
            def fetchall(self):
                if fault == "db-stale" and stage == "update": return [(name, "created", "")]
                if fault == "db-phantom" and stage == "delete": return [(name, "persisted-update", "")]
                if fault == "db-missing" and stage == "create": return []
                return [(key, value["comment"], value["definition"]) for key, value in sorted(state.items())]
        class Database:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cursor(self): return Cursor()
        pg = types.ModuleType("psycopg2")
        pg.connect = lambda **kwargs: Database()
        oauth = types.ModuleType("oauthlib.oauth1")
        oauth.SIGNATURE_PLAINTEXT = "unit-fixture"
        oauth.Client = lambda *args, **kwargs: types.SimpleNamespace(sign=lambda url, **kw: (url, {"Authorization": "unit-fixture"}, None))
        with patch.dict(os.environ, {"MAAS_VERSION": "3.6.5"}), \
             patch.dict(sys.modules, {"requests": requests, "psycopg2": pg, "oauthlib.oauth1": oauth}), \
             patch.object(Path, "read_text", return_value="unit-consumer:unit-token:unit-secret"), \
             patch("uuid.uuid4", return_value=types.SimpleNamespace(hex="a" * 32)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            exec(compile(self.job["env"]["MAAS_API_PROOF"], "workflow:MAAS_API_PROOF", "exec"), {})
        return output.getvalue()

    def test_api_assertions_reject_wrong_identity_auth_crud_and_database_state(self):
        self.assertIn("MAAS_API_POSTGRES_PROOF_PASSED", self.api_assertions())
        for fault in ("version", "unauthorized", "created-name", "created-comment", "stale-update",
                      "delete-status", "db-stale", "db-phantom", "db-missing"):
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                self.api_assertions(fault)

    def test_production_handler_is_used_without_domain_or_auth_substitutions(self):
        server = self.job["env"]["MAAS_API_SERVER"]
        self.assertIn("WebApplicationHandler()", server)
        self.assertIn("yield start_up(master=True)", server)
        self.assertIn("crochet.no_setup()", server)
        self.assertIn("interface='127.0.0.1'", server)
        smoke = self.steps["test5"]["run"]
        self.assertIn("maas-region dbupgrade", smoke)
        self.assertIn("maas-region migrate --check", smoke)
        self.assertIn("test ! -e /smoke/pgdata", smoke)
        self.assertNotIn("--fake", smoke)


if __name__ == "__main__":
    unittest.main()
