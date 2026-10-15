"""Execute the Prophet workflow's Bash and Python probes with explicit fixtures."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_observation_migration_audit as observation_audit


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-prophet.yml"


class ProphetWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="prophet-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-prophet"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, **self.job["env"], RUNNER_TEMP=str(self.root),
                        TMPDIR=str(self.root), GITHUB_OUTPUT=str(self.root / "output"),
                        FIXTURE_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1",
                        FIXTURE_ROOT=str(self.root), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.values = {"steps.install.outputs.install_mode": "github_source"}

    def stub(self, name, content):
        path = self.bin / name
        path.write_text("#!/bin/bash\nset -euo pipefail\n" + content)
        path.chmod(0o755)

    def run_script(self, script, values=None, **env):
        values = {**self.values, **(values or {})}

        def expression(match):
            for term in match[1].split("||"):
                key = term.strip()
                value = key[1:-1] if key.startswith("'") else values.get(key)
                if value:
                    return str(value)
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, script)
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                cwd=self.root, env=dict(self.env, **env),
                                capture_output=True, text=True, timeout=20)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if line)
        return result, outputs

    def run_step(self, name, values=None, **env):
        return self.run_script(self.steps[name]["run"], values, **env)

    def runtime_fixture(self):
        source = self.root / "baseline-src/python/prophet"
        source.mkdir(parents=True)
        (source / "__version__.py").write_text('__version__ = "1.1.1"\n')
        self.stub("uname", 'echo "${FIXTURE_ARCH:-aarch64}"\n')
        self.stub("git", 'test "$*" = "describe --tags --exact-match HEAD"\necho "${FIXTURE_TAG:-v1.1.1}"\n')
        self.stub("timeout", r'''
case "$1:$2" in --kill-after=10s:300s|--kill-after=5s:120s) ;; *) exit 97 ;; esac
shift 2
exec "$@"
''')
        helper = self.root / "fixture-python.py"
        self.env["FIXTURE_HELPER"] = str(helper)
        self.stub("python3", 'exec "$FIXTURE_PYTHON" "$FIXTURE_HELPER" "$@"\n')
        helper.write_text(r'''
import datetime
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import struct
import sys
import types

root = Path(os.environ['FIXTURE_ROOT'])
args = sys.argv[1:]
if args[:2] == ['-m', 'venv']:
    target = Path(args[2]) / 'bin/python'
    target.parent.mkdir()
    shutil.copyfile(root / 'bin/python3', target)
    target.chmod(0o755)
    sys.exit(0)
if args[:2] == ['-m', 'compileall']:
    os.execv(sys.executable, [sys.executable] + args)
if args[:3] == ['-m', 'pip', 'install']:
    print('pip-diagnostic ' + ' '.join(args))
    assert 'setuptools<82' in args
    if '--upgrade' in args:
        assert 'pip' in args and 'wheel' in args
        sys.exit(int(os.environ.get('FIXTURE_BOOTSTRAP_RC', '0')))
    assert '--only-binary=prophet' in args and 'prophet==1.1.1' in args
    assert 'holidays<0.25' in args and 'cmdstanpy<1.3' in args
    assert '--report' in args
    sys.exit(int(os.environ.get('FIXTURE_INSTALL_RC', '0')))
assert args == ['-'], args
code = sys.stdin.read()
if 'from importlib.metadata import version' not in code:
    exec(compile(code, '<workflow-source-probe>', 'exec'))
    sys.exit(0)

# These modules model probe inputs only; actual Stan execution is proven natively.
class Series(list):
    def tail(self, count): return Series(self[-count:])
    def tolist(self): return list(self)
    def notna(self): return Series(x is not None and not math.isnan(x) for x in self)
    def all(self): return all(self)

class Frame:
    def __init__(self, data): self.data = data
    def __len__(self): return len(next(iter(self.data.values())))
    def __getitem__(self, key):
        return Frame({k: self.data[k] for k in key}) if isinstance(key, list) else Series(self.data[key])
    def tail(self, count): return Frame({k: v[-count:] for k, v in self.data.items()})
    def to_string(self, index): return repr(self.data)

def dates(start, periods, freq):
    assert freq == 'D'
    first = datetime.date.fromisoformat(start)
    return Series((first + datetime.timedelta(days=i)).isoformat() for i in range(periods))

binary = root / 'fixture-package/stan_model/prophet_model.bin'
binary.parent.mkdir(parents=True, exist_ok=True)
header = bytearray(64)
header[:6] = b'\x7fELF\x02\x01'
header[18:20] = struct.pack('<H', int(os.environ.get('FIXTURE_ELF_MACHINE', '183')))
if os.environ.get('FIXTURE_ELF_CLASS') == '32': header[4] = 1
binary.write_bytes(b'' if os.environ.get('FIXTURE_EMPTY_MODEL') else header)
csv = root / 'fixture-fit.csv'

class Prophet:
    def __init__(self, **kwargs):
        assert kwargs == dict(daily_seasonality=False, weekly_seasonality=False,
                              yearly_seasonality=False, stan_backend='CMDSTANPY')
        executable = str(binary) + ('.wrong' if os.environ.get('FIXTURE_WRONG_MODEL') else '')
        self.stan_backend = types.SimpleNamespace(
            get_type=lambda: os.environ.get('FIXTURE_BACKEND', 'CMDSTANPY'),
            model=types.SimpleNamespace(exe_file=executable),
            stan_fit=types.SimpleNamespace(runset=types.SimpleNamespace(csv_files=[str(csv)])))
        self.fitted = False
    def fit(self, frame):
        assert frame['ds'].tolist() == dates('2024-01-01', 24, 'D')
        assert frame['y'].tolist() == [float(i % 7) for i in range(24)]
        if os.environ.get('FIXTURE_FIT_FAIL'): raise RuntimeError('fixture fit failure')
        self.fitted = True
        minor = os.environ.get('FIXTURE_STAN_MINOR', '26')
        csv.write_text(f'# stan_version_major = 2\n# stan_version_minor = {minor}\n# stan_version_patch = 1\n')
    def make_future_dataframe(self, periods):
        assert self.fitted and periods == 3
        return Frame({'ds': dates('2024-01-01', 27, 'D')})
    def predict(self, future):
        assert self.fitted and len(future) == 27
        count = int(os.environ.get('FIXTURE_FORECAST_ROWS', '27'))
        values = [3.0] * count
        bad = os.environ.get('FIXTURE_PREDICTION')
        if bad and values: values[-1] = None if bad == 'none' else float(bad)
        start = '2024-02-01' if os.environ.get('FIXTURE_WRONG_DATES') else '2024-01-01'
        return Frame({'ds': dates(start, count, 'D'), 'yhat': values})

pd = types.ModuleType('pandas')
pd.DataFrame, pd.date_range = Frame, dates
package = types.ModuleType('prophet')
package.Prophet = Prophet
package.__file__ = str(binary.parent.parent / '__init__.py')
package.__version__ = os.environ.get('FIXTURE_MODULE_VERSION', '1.1.1')
sys.modules.update(pandas=pd, prophet=package)
importlib.metadata.version = lambda name: os.environ.get('FIXTURE_DIST_VERSION', '1.1.1') if name == 'prophet' else 'fixture'
platform.machine = lambda: os.environ.get('FIXTURE_RUNTIME_ARCH', 'aarch64')
platform.python_version = lambda: '3.10.21-fixture'
sys.version_info = (3, int(os.environ.get('FIXTURE_PYTHON_MINOR', '10')), 21)
exec(compile(code, '<workflow-runtime-probe>', 'exec'))
''')

    def passing(self):
        return {key: value for i in range(1, 7) for key, value in (
            (f"steps.test{i}.outputs.status", "passed"), (f"steps.test{i}.outcome", "success"))}

    def test_runtime_outputs_are_visible_to_existing_observation_audit(self):
        step = self.steps["test5"]
        for output, default in (("status", "failed"), ("duration", "0")):
            with self.subTest(output=output):
                self.assertTrue(observation_audit._step_emits_output(
                    WORKFLOW.parents[2], step, output,
                ))
                without_default = dict(step, run=step["run"].replace(
                    f'echo "{output}={default}" >> "$GITHUB_OUTPUT"\n', "", 1,
                ))
                self.assertFalse(observation_audit._step_emits_output(
                    WORKFLOW.parents[2], without_default, output,
                ))

    def test_runtime_executes_version_bound_fit_and_three_day_forecast(self):
        self.runtime_fixture()
        result, output = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", output["status"])
        self.assertEqual("1.1.1", output["installed_version"])
        self.assertTrue(output["duration"].isdigit())
        proof = json.loads(next(self.root.glob("prophet-logs.*/runtime.json")).read_text())
        self.assertEqual("2.26.1", proof["stan_version"])
        self.assertEqual(27, proof["forecast_rows"])
        self.assertEqual([3.0] * 3, proof["future_yhat"])
        self.assertRegex(proof["model_sha256"], r"^[a-f0-9]{64}$")

    def test_runtime_rejects_wrong_versions_architecture_model_and_forecast(self):
        self.runtime_fixture()
        cases = ({"FIXTURE_DIST_VERSION": "1.4.0"}, {"FIXTURE_MODULE_VERSION": "1.4.0"},
                 {"FIXTURE_ARCH": "x86_64"}, {"FIXTURE_RUNTIME_ARCH": "x86_64"},
                 {"FIXTURE_PYTHON_MINOR": "12"}, {"FIXTURE_ELF_MACHINE": "62"},
                 {"FIXTURE_ELF_CLASS": "32"}, {"FIXTURE_EMPTY_MODEL": "1"},
                 {"FIXTURE_WRONG_MODEL": "1"}, {"FIXTURE_BACKEND": "unrelated"},
                 {"FIXTURE_STAN_MINOR": "33"}, {"FIXTURE_FIT_FAIL": "1"},
                 {"FIXTURE_FORECAST_ROWS": "0"}, {"FIXTURE_FORECAST_ROWS": "26"},
                 {"FIXTURE_PREDICTION": "none"}, {"FIXTURE_PREDICTION": "nan"},
                 {"FIXTURE_PREDICTION": "inf"}, {"FIXTURE_WRONG_DATES": "1"})
        for env in cases:
            with self.subTest(env=env):
                result, output = self.run_step("test5", **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", output["status"])
                self.assertTrue(output["duration"].isdigit())
                self.assertNotIn("installed_version", output)

    def test_source_tag_version_and_compilation_cannot_be_substituted(self):
        self.runtime_fixture()
        for values, env in (({}, {"FIXTURE_TAG": "v1.4.0"}),
                            ({"steps.install.outputs.install_mode": "external_artifact"}, {}),
                            ({"steps.install.outputs.install_mode": ""}, {})):
            result, output = self.run_step("test5", values, **env)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", output["status"])
        source = self.root / "baseline-src/python/prophet/__version__.py"
        for content in ('__version__ = "1.4.0"', '', 'not valid Python!'):
            source.write_text(content)
            result, output = self.run_step("test5")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", output["status"])
        source.write_text('__version__ = "1.1.1"')
        (source.parent / "broken.py").write_text('not valid Python!')
        result, output = self.run_step("test5")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])

    def test_pip_failures_expose_logs_and_never_claim_installed(self):
        self.runtime_fixture()
        for variable in ("FIXTURE_BOOTSTRAP_RC", "FIXTURE_INSTALL_RC"):
            for rc in (1, 22, 23):
                with self.subTest(variable=variable, rc=rc):
                    result, output = self.run_step("test5", **{variable: str(rc)})
                    self.assertEqual(rc, result.returncode)
                    self.assertEqual("failed", output["status"])
                    self.assertIn("pip-diagnostic", result.stdout)
                    self.assertNotIn("installed_version", output)

    def test_late_failure_overrides_an_earlier_pass_output(self):
        self.runtime_fixture()
        script = self.steps["test5"]["run"] + '\necho status=passed >> "$GITHUB_OUTPUT"\nexit 23\n'
        result, output = self.run_script(script)
        self.assertEqual(23, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertTrue(output["duration"].isdigit())

    def test_summary_requires_passed_output_and_actual_success(self):
        self.assertEqual("bash", self.steps["summary"]["shell"])
        result, output = self.run_step("summary", self.passing())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("6", output["passed"])
        for i in range(1, 7):
            for field, value in (("outputs.status", ""), ("outputs.status", "skipped"),
                                 ("outputs.status", "failed"), ("outputs.status", "invalid"),
                                 ("outcome", ""), ("outcome", "failure"),
                                 ("outcome", "cancelled"), ("outcome", "skipped")):
                with self.subTest(i=i, field=field, value=value):
                    values = {**self.passing(), f"steps.test{i}.{field}": value,
                              f"steps.test{i}.conclusion": "success"}
                    result, output = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("5", output["passed"])
                    self.assertEqual("1", output["failed"])
                    self.assertEqual(str(int(i < 6)), output["core_failed"])
                    self.assertEqual("failure", output["overall_status"])
        result, output = self.run_step("summary")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("5", output["core_failed"])
        self.assertEqual("6", output["failed"])
        self.assertEqual("0", output["skipped"])

    def test_only_successful_no_newer_candidate_skip_is_accepted(self):
        for decision in ("", "no_newer_stable_available", "not_configured", "runtime_validation_not_automated"):
            for outcome in ("success", "", "failure", "cancelled", "skipped"):
                values = {**self.passing(), "steps.test6.outputs.status": "skipped",
                          "steps.test6.outcome": outcome, "steps.test6.outputs.decision": decision}
                result, output = self.run_step("summary", values)
                accepted = decision == "no_newer_stable_available" and outcome == "success"
                self.assertEqual(accepted, result.returncode == 0)
                self.assertEqual(str(int(accepted)), output["skipped"])

    def test_candidate_compile_only_never_reports_an_installed_runtime(self):
        self.assertEqual("1.1.1", self.job["env"]["BASELINE_VERSION"])
        self.assertEqual("not_installed", self.job["outputs"]["regression_next_installed_version"])
        summary = next(step for step in self.job["steps"] if step.get("uses", "").endswith("write-package-job-summary"))
        self.assertEqual("not_installed", summary["with"]["regression_next_installed_version"])
        candidate = self.steps["test6"]["with"]
        self.assertEqual('python3 "$GITHUB_WORKSPACE/.github/actions/generic-source-regression-check/limited_cpu_probe.py" next-src\n',
                         candidate["limited_cpu_probe"])
        self.assertIn("without claiming a full Stan-backed modeling runtime", candidate["limited_cpu_description"])
        setup = next(step for step in self.job["steps"] if step.get("uses", "").startswith("actions/setup-python@"))
        self.assertEqual("3.10", setup["with"]["python-version"])


if __name__ == "__main__":
    unittest.main()
