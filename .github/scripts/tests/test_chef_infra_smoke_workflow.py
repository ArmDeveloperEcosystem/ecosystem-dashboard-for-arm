"""Local rejection and contract fixtures; no Chef install or hosted execution."""
import itertools
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
SCRIPTS = ROOT / ".github/scripts"
WORKFLOW = ROOT / ".github/workflows/test-chef-infra.yml"
BASE_SHA = "d28f552c2b23b738d670d348d3c19d24e3c874e8"
NEXT_SHA = "dad75f495067c88d1e07c3f5999d88ef8b3f3cf9"
sys.path.insert(0, str(SCRIPTS))
import package_result_policy as policy  # noqa: E402


class ChefInfraSmokeWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="chef-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-chef-infra"]
        self.steps = {s["id"]: s for s in self.job["steps"] if "id" in s}
        self.values = {"steps.dependencies.outcome": "success", "steps.install.outcome": "success",
                       "steps.test1.outputs.version": "18.8.54", "steps.test6.outputs.decision": "validated_next_release"}
        for n in range(1, 7):
            self.values.update({f"steps.test{n}.outputs.status": "passed", f"steps.test{n}.outcome": "success",
                                f"steps.test{n}.outputs.duration": str(n)})
        self.output = self.root / "outputs"
        self.env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GITHUB_OUTPUT": str(self.output),
                    "GITHUB_WORKSPACE": str(ROOT), "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
                    "CHEF_WORK_ROOT": str(self.root / "work"), "CHEF_VERSION": "18.8.54", "CHEF_NEXT_VERSION": "18.10.17",
                    "CHEF_LICENSE": "", "CHEF_LICENSE_KEY": "", "GEMFILE_MOD": "", "RUBYOPT": "", "HOME": str(self.root)}

    def render(self, source, values):
        def val(term):
            term = term.strip()
            return term[1:-1] if term.startswith("'") and term.endswith("'") else values.get(term, "")

        def expression(match):
            text = match[1]
            if "==" in text:
                return str(all(val(a) == val(b) for a, b in (part.split("==") for part in text.split("&&")))).lower()
            return next((val(p) for p in text.split("||") if val(p)), "")
        return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)

    def shell(self, source, env=None):
        self.output.write_text("")
        result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", source], cwd=ROOT,
                                env={**self.env, **(env or {})}, capture_output=True, text=True, timeout=15)
        pairs = [line.split("=", 1) for line in self.output.read_text().splitlines()]
        self.assertEqual(len(pairs), len(dict(pairs)), "Duplicate output keys")
        return result, dict(pairs)

    def run_step(self, name, overrides=None, prelude="", environment=None):
        step = self.steps[name]
        values = {**self.values, **(overrides or {})}
        env = {k: self.render(str(v), values) for k, v in step.get("env", {}).items()}
        return self.shell(prelude + "\n" + self.render(step["run"], values), {**env, **(environment or {})})

    def test_contract_scope_and_single_action(self):
        self.assertEqual("2.0", self.job["outputs"]["contract_version"])
        self.assertEqual("Chef Infra (source file-resource API only)", self.job["outputs"]["package_name"])
        self.assertEqual("Test 6 - Regression Validation", self.steps["test6"]["name"])
        self.assertEqual("applicable", self.job["outputs"]["regression_policy"])
        actions = [s for s in self.job["steps"] if "uses" in s]
        self.assertEqual(1, len(actions))
        self.assertFalse(actions[0]["with"]["persist-credentials"])
        self.assertIn("# original: actions/checkout@v4", WORKFLOW.read_text())
        for n in range(1, 7):
            step = self.steps[f"test{n}"]
            self.assertEqual("always()", step["if"])
            self.assertNotIn("continue-on-error", step)
            self.assertTrue(step["name"].startswith(f"Test {n} -"))
            if n < 6:
                self.assertNotIn("regression", step["name"].lower())
        source = WORKFLOW.read_text() + "".join((SCRIPTS / p).read_text() for p in
                 ("chef_source_setup.sh", "chef_source_probe.rb", "chef_upstream_file_specs.rb"))
        for forbidden in ("packages.chef.io", "chef-apply", "chef-client", "accept-silent", "accept-no-persist", "bundle exec rake"):
            self.assertNotIn(forbidden, source)

    def test_summary_all_64_failure_combinations(self):
        for failures in itertools.product((False, True), repeat=6):
            values = {}
            for n, failed in enumerate(failures, 1):
                if failed:
                    values.update({f"steps.test{n}.outputs.status": "failed", f"steps.test{n}.outcome": "failure"})
            result, output = self.run_step("summary", values)
            self.assertEqual(int(any(failures)), result.returncode, result.stderr)
            self.assertEqual((str(6-sum(failures)), str(sum(failures)), str(sum(failures[:5])), "21"),
                             tuple(output[k] for k in ("passed", "failed", "core_failed", "duration")))

    def test_missing_status_outcome_setup_and_decision_stay_red(self):
        cases = [{f"steps.test{n}.{field}": value} for n in range(1, 7)
                 for field in ("outputs.status", "outcome") for value in ("", "failed", "skipped", "cancelled")]
        cases += [{key: ""} for key in ("steps.install.outcome", "steps.dependencies.outcome", "steps.test6.outputs.decision")]
        for case in cases:
            result, output = self.run_step("summary", case)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failure", output["overall_status"])

    def test_missing_setup_fails_every_baseline_check(self):
        for n in range(1, 6):
            result, output = self.run_step(f"test{n}")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("failed", output["status"])
            self.assertRegex(output["duration"], r"^\d+$")

    def test_wrong_checkout_sha_rejected_before_dependencies(self):
        result, output = self.shell('''
git() { if [ "$3" = rev-parse ]; then printf '%040d\n' 0; fi; }
bundle() { echo 'UNEXPECTED BUNDLE' >&2; return 99; }
source .github/scripts/chef_source_setup.sh baseline
chef_start_check
chef_setup
''')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("failed", output["status"])
        self.assertNotIn("UNEXPECTED BUNDLE", result.stderr)
        self.assertFalse((self.root / "work/baseline/evidence/setup.complete").exists())

    def test_missing_dependencies_cannot_mark_setup_ready(self):
        result, output = self.shell('''
git() {
  if [ "${3:-}" = rev-parse ] || [ "$1" = rev-parse ]; then echo "$EXPECTED_CHEF_REVISION"; fi
  if [ "${3:-}" = checkout ]; then
    printf 'fixture\n' > "$2/Gemfile"
    printf 'fixture\n' > "$2/Gemfile.lock"
    printf 'fixture\n' > "$2/chef.gemspec"
  fi
  return 0
}
sha256sum() { shasum -a 256 "$@"; }
bundle() { echo 'Dependency fixture failed' >&2; return 43; }
source .github/scripts/chef_source_setup.sh baseline
chef_start_check
chef_setup
''')
        self.assertEqual(43, result.returncode, result.stderr)
        self.assertEqual("failed", output["status"])
        self.assertFalse((self.root / "work/baseline/evidence/setup.complete").exists())

    def test_baseline_guard_is_truthful_skip_and_red_summary(self):
        values = {"steps.test3.outcome": "failure", "steps.test3.outputs.status": "failed"}
        result, output = self.run_step("test6", values, prelude="git() { echo UNEXPECTED >&2; return 99; }")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("skipped", "baseline_failed", "not_installed"),
                         tuple(output[k] for k in ("status", "decision", "next_installed_version")))
        self.assertNotIn("UNEXPECTED", result.stderr)
        values.update({f"steps.test6.outputs.{k}": v for k, v in output.items()})
        result, summary = self.run_step("summary", values)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("4", "1", "1", "1"), tuple(summary[k] for k in ("passed", "failed", "skipped", "core_failed")))

    def test_baseline_and_candidate_paths_are_isolated(self):
        paths = []
        for lane in ("baseline", "candidate"):
            result, _ = self.shell(f"source .github/scripts/chef_source_setup.sh {lane}\nprintf '%s\\n' \"$CHEF_SOURCE_ROOT\" \"$BUNDLE_PATH\" \"$EVIDENCE_DIR\" \"$EXPECTED_CHEF_REVISION\"")
            self.assertEqual(0, result.returncode)
            paths.append(result.stdout.splitlines())
        self.assertEqual(BASE_SHA, paths[0][-1])
        self.assertEqual(NEXT_SHA, paths[1][-1])
        self.assertTrue(set(paths[0]).isdisjoint(paths[1]))

    def test_candidate_executes_functional_coverage_and_propagates_each_failure(self):
        prelude = '''
git() {
  if [ "${3:-}" = rev-parse ] || [ "$1" = rev-parse ]; then echo "$EXPECTED_CHEF_REVISION"; fi
  if [ "${3:-}" = checkout ]; then
    printf 'fixture\n' > "$2/Gemfile"
    printf 'fixture\n' > "$2/Gemfile.lock"
    printf 'fixture\n' > "$2/chef.gemspec"
  fi
  return 0
}
sha256sum() { shasum -a 256 "$@"; }
bundle() {
  printf '%s\n' "$*" >> "$TRACE"
  case "$2" in
    install) [ "$FAIL_PHASE" != install ] || return 43 ;;
    check) [ "$FAIL_PHASE" != check ] || return 44 ;;
    exec)
      case "$4" in
        *chef_source_probe.rb)
          [ "$FAIL_PHASE" != probe ] || return 45
          if [ "$FAIL_PHASE" = version ]; then
            echo 18.0.0 > "$EVIDENCE_DIR/source-version.txt"
          else
            echo "$EXPECTED_CHEF_VERSION" > "$EVIDENCE_DIR/source-version.txt"
          fi
          ;;
        *chef_upstream_file_specs.rb)
          [ "$FAIL_PHASE" != specs ] || return 46
          echo '3 registered, 2 executed, 1 filtered, 0 failed, 0 pending, 0 outside-example errors' > "$EVIDENCE_DIR/spec-summary.txt"
          ;;
        *) return 97 ;;
      esac ;;
    *) return 98 ;;
  esac
  return 0
}
'''
        for phase in ("none", "install", "check", "probe", "version", "specs"):
            work = self.root / phase
            baseline = work / "baseline/evidence"
            baseline.mkdir(parents=True)
            (baseline / "spec-summary.txt").write_text("3 registered, 2 executed, 1 filtered")
            trace = self.root / (phase + ".trace")
            result, output = self.run_step("test6", prelude=prelude,
                environment={"CHEF_WORK_ROOT": str(work), "TRACE": str(trace), "FAIL_PHASE": phase})
            self.assertEqual(phase == "none", result.returncode == 0, result.stderr)
            self.assertEqual("passed" if phase == "none" else "failed", output["status"])
            self.assertEqual("validated_next_release" if phase == "none" else "next_regression_failed", output["decision"])
            if phase == "none":
                self.assertIn("chef_source_probe.rb all", trace.read_text())
                self.assertIn("chef_upstream_file_specs.rb", trace.read_text())
                self.assertEqual("18.10.17", output["next_installed_version"])
                self.assertIn("1 filtered", output["comparison"])
                self.assertIn("vendor CLI and .deb distributions were not tested", output["comparison"])

    @staticmethod
    def good_rspec_case():
        return {"discovered": ["a", "b", "c"], "selected": ["a", "b"],
                "report": {"examples": [{"id": "a", "status": "passed"}, {"id": "b", "status": "passed"}],
                           "summary": {"example_count": 2, "failure_count": 0, "pending_count": 0,
                                       "errors_outside_of_examples_count": 0}}}

    def rspec_fixture(self, case):
        fixture = self.root / "lib/rspec"
        fixture.mkdir(parents=True, exist_ok=True)
        (fixture / "core.rb").write_text('''
require 'json'
module RSpec
  Example = Struct.new(:id, :full_description, :metadata)
  Group = Struct.new(:examples) do
    def descendants; [self]; end
  end
  World = Struct.new(:example_groups, :filtered_examples)
  def self.world; @world; end
  module Core
    class Runner
      def self.run(args)
        config = JSON.parse(File.read(ENV.fetch('CASE_PATH')))
        examples = config.fetch('discovered').map { |id| RSpec::Example.new(id, id, {file_path: 'file_spec.rb', line_number: 1, windows_only: true}) }
        group = RSpec::Group.new(examples)
        selected = examples.select { |e| config.fetch('selected').include?(e.id) }
        RSpec.instance_variable_set(:@world, RSpec::World.new([group], {group => selected}))
        File.write(args.last, JSON.generate(config.fetch('report'))) unless config['missing_report']
        config.fetch('exit_status', 0)
      end
    end
  end
end
''')
        case_path = self.root / "case.json"
        case_path.write_text(json.dumps(case))
        evidence = self.root / "evidence"
        evidence.mkdir(exist_ok=True)
        (evidence / "upstream-rspec.json").unlink(missing_ok=True)
        return subprocess.run(["ruby", "-I", str(fixture.parent), str(SCRIPTS / "chef_upstream_file_specs.rb")],
                              env={**self.env, "CASE_PATH": str(case_path), "EVIDENCE_DIR": str(evidence),
                                   "EXPECTED_CHEF_VERSION": "18.8.54", "EXPECTED_CHEF_REVISION": BASE_SHA},
                              capture_output=True, text=True, timeout=15)

    def test_rspec_discloses_exclusions(self):
        result = self.rspec_fixture(self.good_rspec_case())
        self.assertEqual(0, result.returncode, result.stderr)
        inventory = json.loads((self.root / "evidence/upstream-selection.json").read_text())
        self.assertEqual((3, 2, 1), tuple(inventory[k] for k in ("discovered_examples", "executed_examples", "excluded_examples")))
        self.assertEqual("c", inventory["exclusions"][0]["id"])
        self.assertEqual({"windows_only": True}, inventory["exclusions"][0]["boolean_tags"])

    def test_rspec_rejects_failed_pending_outside_zero_missing_and_wrong_ids(self):
        cases = []
        for field in ("failure_count", "pending_count", "errors_outside_of_examples_count"):
            case = self.good_rspec_case()
            case["report"]["summary"][field] = 1
            cases.append(case)
        for ids in (["a", "a"], ["a", "x"]):
            case = self.good_rspec_case()
            case["report"]["examples"] = [{"id": i, "status": "passed"} for i in ids]
            cases.append(case)
        case = self.good_rspec_case()
        case["selected"], case["report"]["examples"], case["report"]["summary"]["example_count"] = [], [], 0
        cases.append(case)
        for field, value in (("missing_report", True), ("exit_status", 23)):
            case = self.good_rspec_case()
            case[field] = value
            cases.append(case)
        case = self.good_rspec_case()
        case["report"]["examples"][0]["status"] = "failed"
        cases.append(case)
        for case in cases:
            result = self.rspec_fixture(case)
            self.assertNotEqual(0, result.returncode, result.stdout)

    def test_probe_rejects_wrong_loaded_version_and_sha(self):
        lib = self.root / "fake-lib"
        (lib / "chef/resource").mkdir(parents=True)
        (lib / "chef/resource/file.rb").write_text("")
        (lib / "ohai.rb").write_text("")
        (lib / "chef.rb").write_text('''
module Chef; VERSION = ENV.fetch('FIXTURE_VERSION'); end
module Open3
  def self.capture2(*args)
    [ENV.fetch('FIXTURE_SHA'), Struct.new(:success?).new(true)]
  end
end
''')
        for version, revision in (("18.0.0", BASE_SHA), ("18.8.54", "0" * 40)):
            result = subprocess.run(["ruby", "-I", str(lib), str(SCRIPTS / "chef_source_probe.rb"), "identity"], cwd=self.root,
                                    env={**self.env, "FIXTURE_VERSION": version, "FIXTURE_SHA": revision,
                                         "EXPECTED_CHEF_VERSION": "18.8.54", "EXPECTED_CHEF_REVISION": BASE_SHA,
                                         "CHEF_SOURCE_ROOT": str(self.root), "EVIDENCE_DIR": str(self.root)},
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("FAILED: exact", result.stderr)
            self.assertFalse((self.root / "identity.json").exists())

    def collect(self, summary, values, conclusions):
        action = yaml.safe_load((ROOT / ".github/actions/collect-batch-results/action.yml").read_text())
        source = action["runs"]["steps"][0]["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        bindings = {**self.values, **values, **{f"steps.summary.outputs.{k}": v for k, v in summary.items()},
                    "steps.metadata.outputs.package_slug": "chef-infra"}
        outputs = {k: self.render(str(v), bindings) for k, v in self.job["outputs"].items()}
        job = {"id": 456, "name": "test-chef-infra / test-chef-infra", "conclusion": summary["overall_status"],
               "html_url": "https://github.com/example/project/actions/runs/123/job/456",
               "steps": [{"name": self.steps[f"test{i}"]["name"], "number": i, "conclusion": s}
                         for i, s in enumerate(conclusions, 1)]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".github").mkdir()
            (root / ".github/scripts").symlink_to(SCRIPTS)
            process = subprocess.run([sys.executable, "-B", "-c", source], cwd=root,
                env={**self.env, "NEEDS_JSON": json.dumps({"test-chef-infra": {"result": summary["overall_status"], "outputs": outputs}}),
                     "RUN_JOBS_JSON": json.dumps({"jobs": [job]}), "BATCH_NUMBER": "19", "BATCH_TITLE": "Batch 19", "GH_TOKEN": "",
                     "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com",
                     "GITHUB_REPOSITORY": "example/project", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"},
                capture_output=True, text=True, timeout=30)
            path = root / "test-results/chef-infra-test-results/chef-infra.json"
            return process, json.loads(path.read_text()) if path.exists() else None

    def test_collector_roundtrip_preserves_scope_and_regression_evidence(self):
        values = {"steps.test6.outputs.regression_result": "Source API: 383 executed; 741 filtered, not executed.",
                  "steps.test6.outputs.comparison": "Both pinned source bundles passed; vendor CLI and .deb were not tested.",
                  "steps.test6.outputs.current_version": "18.8.54", "steps.test6.outputs.latest_version": "18.10.17",
                  "steps.test6.outputs.next_installed_version": "18.10.17"}
        for failed in (False, True):
            current = dict(values)
            if failed:
                current.update({"steps.test6.outputs.status": "failed", "steps.test6.outcome": "failure",
                                "steps.test6.outputs.decision": "next_regression_failed"})
            _, summary = self.run_step("summary", current)
            process, payload = self.collect(summary, current, ["success"] * 5 + ["failure" if failed else "success"])
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            self.assertEqual("Chef Infra (source file-resource API only)", payload["package"]["name"])
            detail = payload["tests"]["details"][5]
            self.assertEqual("Test 6 - Regression Validation", detail["name"])
            self.assertEqual(values["steps.test6.outputs.comparison"], detail["comparison"])
            self.assertEqual(values["steps.test6.outputs.regression_result"], detail["regression_result"])
            self.assertEqual("failure" if failed else "success", policy.validate_publishable_result(payload))
        current = {**values, "steps.test3.outputs.status": "failed", "steps.test3.outcome": "failure"}
        _, summary = self.run_step("summary", current)
        process, payload = self.collect(summary, current, ["success"] * 6)
        self.assertNotEqual(0, process.returncode)
        self.assertIsNone(payload)

    def test_collector_records_real_baseline_failure_and_candidate_guard(self):
        values = {"steps.test3.outputs.status": "failed", "steps.test3.outcome": "failure"}
        result, regression = self.run_step("test6", values)
        self.assertEqual(0, result.returncode)
        values.update({f"steps.test6.outputs.{k}": v for k, v in regression.items()})
        _, summary = self.run_step("summary", values)
        process, payload = self.collect(summary, values, ["success", "success", "failure", "success", "success", "success"])
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        self.assertEqual((4, 1, 1), tuple(payload["tests"][k] for k in ("passed", "failed", "skipped")))
        self.assertEqual("failed", payload["tests"]["details"][2]["status"])
        self.assertEqual("baseline_failed", payload["tests"]["details"][5]["decision"])
        self.assertEqual("failure", policy.validate_publishable_result(payload))

    def test_shell_and_ruby_syntax(self):
        for step in self.job["steps"]:
            if "run" in step:
                result = subprocess.run(["bash", "-n"], input=self.render(step["run"], self.values), capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stderr)
        for name in ("chef_source_probe.rb", "chef_upstream_file_specs.rb"):
            result = subprocess.run(["ruby", "-c", str(SCRIPTS / name)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
        result = subprocess.run(["bash", "-n", str(SCRIPTS / "chef_source_setup.sh")], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
