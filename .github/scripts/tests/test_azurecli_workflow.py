"""Azure CLI source-wheel, exact-runtime and outcome accounting regressions."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
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
                                env={**os.environ, **self.job["env"], "GITHUB_OUTPUT": str(output), **environment},
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


if __name__ == "__main__":
    unittest.main()
