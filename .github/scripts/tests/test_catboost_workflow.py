"""Unit fixtures for CatBoost's Docker boundaries, CPU contract, and summary.

These tests do not compile CatBoost; native build/runtime evidence is separate.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-catboost.yml"
REGRESSION = ROOT / ".github/actions/generic-source-regression-check/action.yml"


class CatBoostWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="catboost-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-catboost"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = dict(os.environ, **self.job["env"])
        self.env.update(
            GITHUB_OUTPUT=str(self.root / "output"), PYTHONPATH=str(self.root),
            FIT_CALLS=str(self.root / "fits.json"), DOCKER_CALLS=str(self.root / "docker-calls"),
            GITHUB_RUN_ID="unit-catboost", GITHUB_RUN_ATTEMPT="1",
        )
        self.tools = self.root / "bin"
        self.tools.mkdir()
        self.env["PATH"] = str(self.tools) + os.pathsep + os.environ["PATH"]
        docker = self.tools / "docker"
        docker.write_text(f"#!{sys.executable}\n" + '''
import json
import os
from pathlib import Path
import subprocess
import sys
args = sys.argv[1:]
with open(os.environ["DOCKER_CALLS"], "a") as calls:
    calls.write(json.dumps(args) + "\\n")
if args[:2] == ["volume", "create"]:
    if os.environ.get("VOLUME_FAIL"):
        sys.exit("volume creation failed")
    Path("volume-" + args[2]).touch()
elif args[:2] == ["volume", "inspect"]:
    sys.exit(0 if Path("volume-" + args[2]).exists() else 1)
elif args[:2] == ["volume", "rm"]:
    if os.environ.get("CLEANUP_FAIL"):
        sys.exit("owned volume cleanup failed")
    Path("volume-" + args[2]).unlink()
elif args[:2] == ["container", "inspect"]:
    sys.exit(1)
elif args[0] == "run":
    assert os.environ["PINNED_CONTAINER_IMAGE_CATBOOST"] in args
    assert all(flag in args for flag in ("--rm", "--cpus=2", "--memory=8g", "--memory-swap=8g", "--pids-limit=512"))
    assert "CATBOOST_CPU_SMOKE=" + os.environ["CATBOOST_CPU_SMOKE"] in args
    if os.environ["FIXTURE_VERSION"] == "1.1.1":
        assert "BASELINE_VERSION=1.1.1" in args
        assert "BASELINE_SOURCE_COMMIT=" + os.environ["BASELINE_SOURCE_COMMIT"] in args
    else:
        assert "EXPECTED_VERSION=" + os.environ["FIXTURE_VERSION"] in args
    payload = sys.stdin.read()
    assert 'test "$(uname -m)" = aarch64' in payload
    for failure in ("DOCKER_FAIL", "VENV_FAIL", "CMAKE_FAIL", "PACKAGING_FAIL"):
        if os.environ.get(failure):
            sys.exit(failure)
    if os.environ.get("TIMEOUT_FAIL"):
        sys.exit(124)
    if os.environ.get("PIP_FAIL"):
        sys.exit("ERROR: No matching distribution found for catboost==" + os.environ["FIXTURE_VERSION"])
    env = dict(os.environ, EXPECTED_VERSION=os.environ["FIXTURE_VERSION"])
    sys.exit(subprocess.run([sys.executable, "-c", env["CATBOOST_CPU_SMOKE"]], env=env).returncode)
else:
    raise AssertionError(args)
''')
        docker.chmod(0o755)
        (self.root / "numpy.py").write_text('''
__version__ = "fixture"
class Array:
    def __init__(self, values):
        self.values = values
        self.shape = (len(values),)
    def reshape(self, size):
        assert size == -1
        return self
    def __iter__(self):
        return iter(self.values)
    def tolist(self):
        return self.values
def array(values, dtype=None):
    return Array(values)
''')
        (self.root / "catboost.py").write_text('''
import json
import os
from pathlib import Path
from numpy import Array
if os.environ.get("IMPORT_FAIL"):
    raise ImportError("native CatBoost extension failed to load")
__version__ = os.environ.get("MODULE_VERSION", os.environ["FIXTURE_VERSION"])
class Pool:
    def __init__(self, X, y):
        self.X, self.y = X, y
class CatBoostClassifier:
    def __init__(self, **parameters):
        self.parameters = parameters
        self.fitted = False
    def fit(self, pool):
        if os.environ.get("FIT_FAIL"):
            raise RuntimeError("CPU training failed")
        Path(os.environ["FIT_CALLS"]).write_text(json.dumps({
            "parameters": self.parameters, "X": pool.X.values, "y": pool.y.values,
        }))
        self.fitted = True
    def predict(self, X):
        assert self.fitted
        if os.environ.get("WRONG_COUNT"):
            return Array([0, 1, 1])
        if os.environ.get("WRONG_LABEL"):
            return Array([0, 0, 1, 2])
        return Array([0, 0, 1, 1])
''')

    def render(self, script, values):
        def expression(match):
            for term in match.group(1).split("||"):
                term = term.strip()
                if term.startswith("'"):
                    return term.strip("'")
                if values.get(term):
                    return str(values[term])
            return ""
        return re.sub(r"\$\{\{ (.*?) \}\}", expression, script)

    def run_step(self, step, statuses=None, outcomes=None, decision="no_newer_stable_available", **extra):
        version = "1.2.10" if step == "candidate" else "1.1.1"
        dist = self.root / "catboost.dist-info"
        dist.mkdir(exist_ok=True)
        dist_version = extra.pop("DIST_VERSION", version)
        (dist / "METADATA").write_text(f"Name: catboost\nVersion: {dist_version}\n")
        if outcomes is None:
            outcomes = {f"test{n}": "success" for n in range(1, 7)}
        values = {f"steps.{key}.outputs.status": value for key, value in (statuses or {}).items()}
        values.update({f"steps.{key}.outcome": value for key, value in outcomes.items()})
        values["steps.test6.outputs.decision"] = decision
        values.update({f"steps.test{n}.outputs.duration": "2" for n in range(1, 7)})
        script = (self.steps["test6"]["with"]["limited_cpu_probe"] if step == "candidate"
                  else self.steps[step]["run"])
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", self.render(script, values)],
            cwd=self.root,
            env=dict(self.env, FIXTURE_VERSION=version, LATEST_VERSION=version, **extra),
            capture_output=True, text=True, timeout=10,
        )
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        return result, outputs

    def test_pinned_baseline_and_existing_python_action_are_preserved(self) -> None:
        self.assertEqual("1.1.1", self.env["BASELINE_VERSION"])
        self.assertEqual("e12502840542f2760dc4e3f3041c9ce8e0814aa4", self.env["BASELINE_SOURCE_COMMIT"])
        self.assertEqual("ubuntu@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc",
                         self.env["PINNED_CONTAINER_IMAGE_CATBOOST"])
        self.assertIn("# original: ubuntu:22.04", WORKFLOW.read_text())
        setup = [s for s in self.job["steps"] if s.get("uses", "").startswith("actions/setup-python@")]
        self.assertEqual(1, len(setup))
        self.assertEqual("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", setup[0]["uses"])
        self.assertEqual("3.10", setup[0]["with"]["python-version"])
        self.assertNotIn("container", self.job)

    def test_source_recipe_is_bounded_pinned_and_not_a_newer_wheel_substitution(self) -> None:
        script = self.steps["test5"]["run"]
        for required in (
            'test "$(git -C /work/catboost rev-parse HEAD)" = "$BASELINE_SOURCE_COMMIT"',
            'test -z "$(git -C /work/catboost status --porcelain)"',
            "-DCMAKE_POSITION_INDEPENDENT_CODE=ON", "-DHAVE_CUDA=OFF",
            "-DCMAKE_TOOLCHAIN_FILE=/work/catboost/clang.toolchain",
            "-DCMAKE_C_FLAGS_RELEASE=-O3 -DNDEBUG -mno-outline-atomics",
            "-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG -mno-outline-atomics",
            "--signal=INT --kill-after=30s 1800 cmake --build /work/build --target _catboost --parallel 2",
            "conan==1.59.0", "setuptools==65.5.1", "wheel==0.38.4", "numpy==1.23.5",
            "mk_wheel.py", "builder.make_wheel(", "--no-deps --force-reinstall /work/catboost-1.1.1-",
            "INSTALLED_EXTENSION_MATCHES_SOURCE_BUILD=", "BUILD_CACHE_PRESENT=yes",
        ):
            self.assertIn(required, script)
        self.assertNotIn('"catboost==$BASELINE_VERSION"', script)
        self.assertNotIn("|| true", script)
        self.assertNotIn("MI_LOCAL_DYNAMIC_TLS", script)
        self.assertNotIn("mimalloc-pic.cmake", script)
        for body in (script, self.steps["test6"]["with"]["limited_cpu_probe"]):
            checked = subprocess.run(["bash", "-n"], input=body, capture_output=True, text=True)
            self.assertEqual(0, checked.returncode, checked.stderr)

    def test_compiler_contract_rejects_missing_pic_arm_or_lld_flags(self) -> None:
        code = self.steps["test5"]["run"].split("python - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        commands = self.root / "commands.txt"

        class RedirectFixture(ast.NodeTransformer):
            def visit_Constant(self, node):
                if node.value == "/work/verified-commands.txt":
                    return ast.copy_location(ast.Constant(str(commands)), node)
                return node

        tree = ast.fix_missing_locations(RedirectFixture().visit(ast.parse(code)))
        for missing in (None, "pic", "arm", "lld", "commands"):
            with self.subTest(missing=missing):
                flags = ["-fPIC", "-mno-outline-atomics"]
                if missing == "pic":
                    flags.remove("-fPIC")
                if missing == "arm":
                    flags.remove("-mno-outline-atomics")
                lines = ["/usr/bin/clang " + " ".join(flags) + " -c /source/example.c"] * (1 if missing == "commands" else 3001)
                if missing != "lld":
                    lines.append("clang++ -fuse-ld=lld -shared -o _catboost.so")
                commands.write_text("\n".join(lines))
                if missing:
                    with self.assertRaises(AssertionError):
                        exec(compile(tree, "workflow-compiler-contract", "exec"), {})
                else:
                    exec(compile(tree, "workflow-compiler-contract", "exec"), {})

    def test_both_versions_train_the_original_tiny_cpu_model(self) -> None:
        for step in ("test5", "candidate"):
            with self.subTest(step=step):
                result, outputs = self.run_step(step)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                fit = json.loads(Path(self.env["FIT_CALLS"]).read_text())
                self.assertEqual({"iterations": 4, "depth": 2, "learning_rate": 0.5,
                                  "loss_function": "Logloss", "verbose": False, "thread_count": 1},
                                 fit["parameters"])
                self.assertEqual([[0, 0], [0, 1], [1, 0], [1, 1]], fit["X"])
                self.assertEqual([0, 0, 1, 1], fit["y"])
                self.assertIn("predictions=[0, 0, 1, 1]", result.stdout)
                if step == "test5":
                    self.assertEqual("passed", outputs["status"])

    def test_source_build_and_environment_failures_emit_baseline_failure(self) -> None:
        for failure in ("VOLUME_FAIL", "DOCKER_FAIL", "CMAKE_FAIL", "PACKAGING_FAIL", "PIP_FAIL", "VENV_FAIL", "TIMEOUT_FAIL"):
            with self.subTest(failure=failure):
                result, outputs = self.run_step("test5", **{failure: "1"})
                self.assertEqual(124 if failure == "TIMEOUT_FAIL" else 1, result.returncode)
                self.assertEqual("failed", outputs["status"])
                self.assertGreaterEqual(int(outputs["duration"]), 0)
                self.assertNotIn("status=passed", Path(self.env["GITHUB_OUTPUT"]).read_text())
                if failure == "PIP_FAIL":
                    self.assertIn("No matching distribution found for catboost==1.1.1", result.stderr)

    def test_cleanup_failure_overrides_a_passed_output(self) -> None:
        result, outputs = self.run_step("test5", CLEANUP_FAIL="1")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", outputs["status"])
        self.assertIn("owned volume cleanup failed", result.stderr)

    def test_container_environment_must_be_explicit(self) -> None:
        script = self.steps["test5"]["run"]
        for name in ("BASELINE_VERSION", "BASELINE_SOURCE_COMMIT", "CATBOOST_CPU_SMOKE"):
            with self.subTest(name=name):
                self.steps["test5"]["run"] = script.replace(f'-e {name}="${name}"', f'-e {name}')
                result, outputs = self.run_step("test5")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("failed", outputs["status"])

    def test_both_versions_reject_import_training_predictions_and_version_mismatch(self) -> None:
        failures = {"IMPORT_FAIL": "1", "FIT_FAIL": "1", "WRONG_COUNT": "1",
                    "WRONG_LABEL": "1", "MODULE_VERSION": "9.9.9", "DIST_VERSION": "9.9.9"}
        for step in ("test5", "candidate"):
            for failure, value in failures.items():
                with self.subTest(step=step, failure=failure):
                    result, outputs = self.run_step(step, **{failure: value})
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("Traceback", result.stderr)
                    if step == "test5":
                        self.assertEqual("failed", outputs["status"])

    def test_candidate_install_failure_is_not_accepted(self) -> None:
        result, _ = self.run_step("candidate", PIP_FAIL="1")
        self.assertEqual(1, result.returncode)
        self.assertIn("No matching distribution found for catboost==1.2.10", result.stderr)
        self.assertNotIn("predictions=", result.stdout)

    def test_summary_requires_passed_output_and_successful_outcome(self) -> None:
        script = self.steps["summary"]["run"]
        self.assertNotIn("check_core_test", script)
        for prefix in ("T", "O", "D"):
            for n in range(1, 7):
                self.assertIn(f'{prefix}{n}="${{{{ steps.test{n}.', script)
        cases = [(None, "passed", "success"), ("all", "", ""), ("test6", "skipped", "success")]
        cases += [(f"test{n}", status, "success") for n in range(1, 7) for status in ("failed", "", "invalid")]
        cases += [(f"test{n}", "passed", outcome) for n in range(1, 7)
                  for outcome in ("failure", "skipped", "cancelled", "")]
        cases += [(f"test{n}", "skipped", "success") for n in range(1, 6)]
        cases += [("test6", "skipped", outcome) for outcome in ("failure", "skipped", "cancelled", "")]
        for changed, status, outcome in cases:
            with self.subTest(changed=changed, status=status, outcome=outcome):
                statuses = {f"test{n}": "passed" for n in range(1, 7)}
                outcomes = {f"test{n}": "success" for n in range(1, 7)}
                if changed == "all":
                    statuses, outcomes = {}, {}
                elif changed:
                    statuses[changed], outcomes[changed] = status, outcome
                result, outputs = self.run_step("summary", statuses=statuses, outcomes=outcomes)
                skipped = int(changed == "test6" and status == "skipped" and outcome == "success")
                failed = 6 if changed == "all" else int(changed is not None and not skipped)
                core = 5 if changed == "all" else int(changed not in (None, "test6"))
                self.assertEqual(int(failed > 0), result.returncode, result.stderr)
                self.assertEqual(str(failed), outputs["failed"])
                self.assertEqual(str(core), outputs["core_failed"])
                self.assertEqual(str(6 - failed - skipped), outputs["passed"])
                self.assertEqual(str(skipped), outputs["skipped"])
                self.assertEqual("12", outputs["duration"])
                self.assertEqual("failure" if failed else "success", outputs["overall_status"])
                self.assertEqual("failing" if core else "passing", outputs["badge_status"])

    def test_summary_rejects_unapproved_skip_decisions(self) -> None:
        statuses = {f"test{n}": "passed" for n in range(1, 6)}
        statuses["test6"] = "skipped"
        for decision in ("", "arbitrary", "deferred", "runtime_validation_not_automated", "baseline_failed", "limited_cpu_smoke_failed"):
            with self.subTest(decision=decision):
                result, outputs = self.run_step("summary", statuses=statuses, decision=decision)
                self.assertEqual(1, result.returncode)
                self.assertEqual("5", outputs["passed"])
                self.assertEqual("1", outputs["failed"])
                self.assertEqual("0", outputs["core_failed"])
                self.assertEqual("0", outputs["skipped"])
                self.assertEqual("failure", outputs["overall_status"])


if __name__ == "__main__":
    unittest.main()
