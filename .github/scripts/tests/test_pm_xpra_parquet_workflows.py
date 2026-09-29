"""Exercise only Xpra/Parquet decisions with the unchanged collector and policy.

Jobs API records are controlled fixtures, not live GitHub observations.
"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
PROTECTED = (".github/actions/collect-batch-results/action.yml",
             ".github/scripts/package_result_policy.py")
sys.path.insert(0, str(ROOT / ".github/scripts"))
from package_result_policy import validate_publishable_result, validate_six_test_result
import package_observation_migration_audit as audit


def render(source, values):
    def replace(match):
        for term in match[1].split('||'):
            term = term.strip()
            if term.startswith("'") and term.endswith("'"):
                return term[1:-1]
            if term.isdigit():
                return term
            if values.get(term):
                return str(values[term])
        return ''
    return re.sub(r'\$\{\{\s*(.*?)\s*\}\}', replace, str(source))


def inputs(slug):
    values = {'steps.install.outcome': 'success',
              'steps.install.outputs.status': 'passed',
              'steps.install.outputs.install_status': 'success',
              'steps.version.outcome': 'success',
              'steps.version.outputs.status': 'passed',
              'steps.version.outputs.version': '1.2.3',
              'steps.metadata.outputs.package_slug': slug,
              'steps.metadata.outputs.timestamp': '2026-09-09T00:00:00Z',
              'steps.metadata.outputs.dashboard_link': '/linux/opensource_packages/' + slug,
              'github.job': 'test-' + slug, 'github.run_id': '123', 'github.run_attempt': '1'}
    for i in range(1, 6):
        values.update({f'steps.test{i}.outputs.status': 'passed',
                       f'steps.test{i}.outcome': 'success',
                       f'steps.test{i}.conclusion': 'success',
                       f'steps.test{i}.outputs.duration': '2'})
    return values


def run_step(step, values, environment):
    with tempfile.TemporaryDirectory(prefix='pm-delta-shell-') as directory:
        output = Path(directory) / 'output'
        output.touch()
        env = {'PATH': os.defpath, 'GITHUB_OUTPUT': str(output), **environment}
        env.update({k: render(v, values) for k, v in step.get('env', {}).items()})
        script = render(step['run'], values)
        result = subprocess.run(['/bin/bash', '-e', '-o', 'pipefail', '-c', script],
                                cwd=directory, env=env, capture_output=True, text=True, timeout=10)
        pairs = [line.split('=', 1) for line in output.read_text().splitlines()]
        assert len(pairs) == len(dict(pairs)), pairs
        return {'rc': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
                'script': script, 'outputs': dict(pairs)}


def collect(source_root, slug, job, values, outcomes):
    action = yaml.safe_load((source_root / PROTECTED[0]).read_text())
    shell = action['runs']['steps'][0]['run']
    program = shell.split("python3 - <<'PY'\n", 1)[1].split('\nPY', 1)[0]
    outputs = {k: render(v, values) for k, v in job['outputs'].items()}
    success = outputs['run_status'] == 'success'
    api_steps = []
    for i, step in enumerate(job['steps'], 1):
        step_id = step.get('id', '')
        if re.fullmatch(r'test[1-6]', step_id):
            api_steps.append({'name': step['name'], 'number': i,
                              'conclusion': outcomes.get(step_id, 'success'),
                              'started_at': '2026-09-09T00:00:00Z',
                              'completed_at': '2026-09-09T00:00:02Z' if step_id != 'test6'
                                              else '2026-09-09T00:00:00Z'})
    api = {'jobs': [{'name': 'test-' + slug, 'id': 456, 'conclusion': 'success' if success else 'failure',
                     'html_url': 'https://github.com/fixture/repo/actions/runs/123/job/456',
                     'steps': api_steps}]}
    needs = {'test-' + slug: {'result': 'success' if success else 'failure', 'outputs': outputs}}
    with tempfile.TemporaryDirectory(prefix='pm-delta-collector-') as directory:
        root = Path(directory)
        (root / '.github/scripts').mkdir(parents=True)
        shutil.copy2(source_root / PROTECTED[1], root / PROTECTED[1])
        (root / 'test-results').mkdir()
        env = {'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1',
               'NEEDS_JSON': json.dumps(needs), 'RUN_JOBS_JSON': json.dumps(api),
               'BATCH_NUMBER': '1', 'BATCH_TITLE': 'Bounded PM fixture', 'GH_TOKEN': '',
               'GITHUB_SERVER_URL': 'https://github.com', 'GITHUB_API_URL': 'https://api.github.com',
               'GITHUB_REPOSITORY': 'fixture/repo', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
               'GITHUB_OUTPUT': str(root / 'output'), 'GITHUB_STEP_SUMMARY': str(root / 'summary')}
        result = subprocess.run([sys.executable, '-B', '-c', program], cwd=root, env=env,
                                capture_output=True, text=True, timeout=10)
        path = root / f'test-results/{slug}-test-results/{slug}.json'
        row = json.loads(path.read_text()) if path.exists() else None
    policies = {}
    if row:
        t = row['tests']
        for name, validate in (
            ('six', lambda: validate_six_test_result(details=t['details'], passed=t['passed'],
                         failed=t['failed'], skipped=t['skipped'], core_failed=row['metadata']['core_failed'],
                         decision=t['details'][5]['decision'])),
            ('publisher', lambda: validate_publishable_result(row)),
        ):
            try:
                policies[name] = validate()
            except ValueError as error:
                policies[name] = str(error)
    return {'rc': result.returncode, 'stderr': result.stderr, 'stdout': result.stdout,
            'row': row, 'policies': policies, 'needs': needs, 'api_fixture': api}


def evaluate(source_root, slug, values, outcomes):
    job = yaml.safe_load((source_root / f'.github/workflows/test-{slug}.yml').read_text())['jobs']['test-' + slug]
    steps = {s.get('id'): s for s in job['steps']}
    values = dict(values)
    env = {k: str(v) for k, v in job.get('env', {}).items()}
    values.update({'env.' + k: v for k, v in env.items()})
    test6 = run_step(steps['test6'], values, env)
    values.update({'steps.test6.outputs.' + k: v for k, v in test6['outputs'].items()})
    values['steps.test6.outcome'] = 'failure' if test6['rc'] else 'success'
    summary = run_step(steps['summary'], values, env)
    values.update({'steps.summary.outputs.' + k: v for k, v in summary['outputs'].items()})
    return {'test6': test6, 'summary': summary, 'collector': collect(source_root, slug, job, values, outcomes)}


class PmXpraParquetTests(unittest.TestCase):
    def test_real_shell_collector_and_publisher_accept_positive_and_core_failures(self):
        for slug in ("xpra", "parquet"):
            for failed in range(6):
                with self.subTest(slug=slug, failed=failed):
                    values = inputs(slug)
                    outcomes = {}
                    if failed:
                        values[f"steps.test{failed}.outputs.status"] = "failed"
                        values[f"steps.test{failed}.outcome"] = "failure"
                        outcomes[f"test{failed}"] = "failure"
                    result = evaluate(ROOT, slug, values, outcomes)
                    decision = "baseline_failed" if failed else "not_applicable_package_manager"
                    self.assertEqual(result["test6"]["outputs"]["decision"], decision)
                    self.assertEqual(result["test6"]["rc"], 0)
                    summary = result["summary"]
                    count = int(bool(failed))
                    self.assertEqual(tuple(summary["outputs"][k] for k in
                        ("passed", "failed", "skipped", "core_failed")),
                        (str(5-count), str(count), "1", str(count)))
                    self.assertEqual(summary["rc"], count)
                    self.assertEqual(int(summary["outputs"]["duration"]),
                                     10 + int(result["test6"]["outputs"]["duration"]))
                    collector = result["collector"]
                    self.assertEqual(collector["rc"], 0, collector["stderr"])
                    expected = "failure" if failed else "success"
                    self.assertEqual(collector["policies"], {"six": expected, "publisher": expected})
                    self.assertEqual(collector["row"]["tests"]["failed"], count)
                    self.assertEqual(collector["row"]["metadata"]["badge_status"],
                                     "failing" if failed else "passing")

    def test_masked_api_failure_is_rejected_without_a_row(self):
        for slug in ("xpra", "parquet"):
            values = inputs(slug)
            values.update({"steps.test5.outputs.status": "failed", "steps.test5.outcome": "failure"})
            result = evaluate(ROOT, slug, values, {})
            collector = result["collector"]
            self.assertEqual(result["test6"]["outputs"]["decision"], "baseline_failed")
            self.assertEqual(collector["rc"], 1)
            self.assertIsNone(collector["row"])
            self.assertIn("emitted failure counts contradict test details", collector["stderr"])

    def load_steps(self, slug):
        job = yaml.safe_load((ROOT / f".github/workflows/test-{slug}.yml").read_text())["jobs"]["test-" + slug]
        return job, {s.get("id"): s for s in job["steps"]}

    def shell_pair(self, slug, values, override=None):
        job, steps = self.load_steps(slug)
        values = dict(values)
        env = job.get("env", {})
        values.update({"env." + k: v for k, v in env.items()})
        test6 = run_step(steps["test6"], values, env)
        values.update({"steps.test6.outputs." + k: v for k, v in test6["outputs"].items()})
        values["steps.test6.outcome"] = "success" if not test6["rc"] else "failure"
        values.update(override or {})
        return test6, run_step(steps["summary"], values, env)

    def test_every_core_status_and_original_outcome_is_required(self):
        for slug in ("xpra", "parquet"):
            for i in range(1, 6):
                for key, bad in (("outputs.status", ("", "failed", "skipped", "unknown")),
                                 ("outcome", ("", "failure", "skipped", "cancelled"))):
                    for value in bad:
                        with self.subTest(slug=slug, i=i, key=key, value=value):
                            values = inputs(slug)
                            values[f"steps.test{i}.{key}"] = value
                            test6, summary = self.shell_pair(slug, values)
                            self.assertEqual(test6["outputs"]["decision"], "baseline_failed")
                            self.assertEqual(summary["rc"], 1)
                            self.assertEqual(tuple(summary["outputs"][k] for k in
                                ("passed", "failed", "skipped", "core_failed")), ("4", "1", "1", "1"))

    def test_install_failure_has_priority_and_never_uses_stale_passes(self):
        for slug in ("xpra", "parquet"):
            status = "status" if slug == "xpra" else "install_status"
            for key, bad in (("outcome", ("", "failure", "skipped", "cancelled")),
                             ("outputs." + status, ("", "failed", "unknown"))):
                for value in bad:
                    for core_failure in (False, True):
                        with self.subTest(slug=slug, key=key, value=value, core_failure=core_failure):
                            values = inputs(slug)
                            values["steps.install." + key] = value
                            if core_failure:
                                values["steps.test1.outputs.status"] = "failed"
                                values["steps.test1.outcome"] = "failure"
                            test6, summary = self.shell_pair(slug, values)
                            self.assertEqual(test6["outputs"]["decision"], "baseline_install_failed")
                            self.assertEqual(summary["rc"], 1)
                            self.assertEqual(summary["outputs"]["badge_status"], "failing")
                            self.assertEqual(summary["outputs"]["core_failed"], str(int(core_failure)))
                            self.assertEqual(summary["outputs"]["skipped"], str(int(core_failure)))

    def test_failed_install_row_is_publishable_when_core_failures_are_visible(self):
        for slug in ("xpra", "parquet"):
            values = inputs(slug)
            values["steps.install.outcome"] = "failure"
            values["steps.install.outputs.status"] = "failed"
            values["steps.install.outputs.install_status"] = "failed"
            for i in range(1, 6):
                values[f"steps.test{i}.outputs.status"] = "failed"
                values[f"steps.test{i}.outcome"] = "failure"
            result = evaluate(ROOT, slug, values, {f"test{i}": "failure" for i in range(1, 6)})
            self.assertEqual(result["test6"]["outputs"]["decision"], "baseline_install_failed")
            self.assertEqual(result["summary"]["outputs"]["failed"], "5")
            self.assertEqual(result["collector"]["rc"], 0, result["collector"]["stderr"])
            self.assertEqual(result["collector"]["policies"], {"six": "failure", "publisher": "failure"})

    def test_version_failure_or_missing_version_cannot_claim_a_valid_pm_baseline(self):
        for slug in ("xpra", "parquet"):
            bad = [("outcome", value) for value in ("", "failure", "skipped", "cancelled")]
            bad += [("outputs.version", "")]
            if slug == "parquet":
                bad += [("outputs.status", value) for value in ("", "failed", "skipped")]
            for key, value in bad:
                values = inputs(slug)
                values["steps.version." + key] = value
                test6, summary = self.shell_pair(slug, values)
                self.assertEqual(test6["outputs"]["decision"], "baseline_failed")
                self.assertEqual(summary["rc"], 1)
                self.assertEqual(summary["outputs"]["core_failed"], "0")
                self.assertEqual(summary["outputs"]["failed"], "1")
                self.assertEqual(summary["outputs"]["skipped"], "0")

    def test_summary_requires_the_exact_decision_status_and_outcome(self):
        for slug in ("xpra", "parquet"):
            for state in ("positive", "core", "install"):
                values = inputs(slug)
                expected = "not_applicable_package_manager"
                if state != "positive":
                    values["steps.test5.outputs.status"] = "failed"
                    values["steps.test5.outcome"] = "failure"
                    expected = "baseline_failed"
                if state == "install":
                    values["steps.install.outcome"] = "failure"
                    expected = "baseline_install_failed"
                for decision in ("not_applicable_package_manager", "baseline_failed",
                                 "baseline_install_failed", "manual_review_needed", "", "unknown"):
                    if decision == expected:
                        continue
                    _, summary = self.shell_pair(slug, values, {"steps.test6.outputs.decision": decision})
                    self.assertEqual(summary["rc"], 1)
                    self.assertEqual(summary["outputs"]["skipped"], "0")
                    self.assertEqual(summary["outputs"]["failed"], "1" if state == "positive" else "2")
                for key, bad in (("outcome", ("", "failure", "skipped", "cancelled")),
                                 ("outputs.status", ("", "passed", "failed", "deferred", "unknown"))):
                    for value in bad:
                        _, summary = self.shell_pair(slug, values, {"steps.test6." + key: value})
                        self.assertEqual(summary["rc"], 1)
                        self.assertEqual(summary["outputs"]["skipped"], "0")

    def test_duration_is_bounded_decimal_and_includes_all_six_steps(self):
        for slug in ("xpra", "parquet"):
            for i in range(1, 7):
                for value in ("-1", "1.5", "1+2", "invalid", "1000000000", " 2"):
                    _, summary = self.shell_pair(slug, inputs(slug), {f"steps.test{i}.outputs.duration": value})
                    self.assertEqual(summary["rc"], 1)
                    self.assertEqual(summary["outputs"], {})
                    self.assertIn("Invalid test duration", summary["stderr"])
            for value, expected in (("08", "48"), ("", "0"), ("0", "0")):
                _, summary = self.shell_pair(slug, inputs(slug),
                    {f"steps.test{i}.outputs.duration": value for i in range(1, 7)})
                self.assertEqual(summary["rc"], 0, summary["stderr"])
                self.assertEqual(summary["outputs"]["duration"], expected)

    def test_unchanged_auditor_recognizes_three_actual_literal_pairs(self):
        expected = {(decision, "skipped") for decision in
                    ("baseline_install_failed", "baseline_failed", "not_applicable_package_manager")}
        for slug in ("xpra", "parquet"):
            _, steps = self.load_steps(slug)
            self.assertEqual(steps["test6"]["if"], "always()")
            self.assertEqual(steps["summary"]["if"], "always()")
            self.assertEqual(set(audit._step_literal_pairs(ROOT, steps["test6"])), expected)
            for key in ("status", "decision", "duration", "current_version", "latest_version",
                        "next_installed_version", "regression_result", "comparison"):
                self.assertTrue(audit._step_emits_output(ROOT, steps["test6"], key), key)
            for key in ("passed", "failed", "skipped", "core_failed", "duration",
                        "overall_status", "badge_status"):
                self.assertTrue(audit._step_emits_output(ROOT, steps["summary"], key), key)

    def test_unchanged_policy_rejects_counter_decision_and_badge_contradictions(self):
        for slug in ("xpra", "parquet"):
            values = inputs(slug)
            values["steps.test5.outputs.status"] = "failed"
            values["steps.test5.outcome"] = "failure"
            row = evaluate(ROOT, slug, values, {"test5": "failure"})["collector"]["row"]
            mutations = (("tests", "failed", 0), ("tests", "skipped", 0),
                         ("metadata", "core_failed", 0), ("metadata", "badge_status", "passing"),
                         ("run", "status", "success"))
            for section, key, value in mutations:
                bad = copy.deepcopy(row)
                bad[section][key] = value
                with self.assertRaises(ValueError):
                    validate_publishable_result(bad)
            bad = copy.deepcopy(row)
            bad["tests"]["details"][5]["decision"] = "not_applicable_package_manager"
            bad["metadata"]["regression_decision"] = "not_applicable_package_manager"
            with self.assertRaisesRegex(ValueError, "baseline failures require"):
                validate_publishable_result(bad)


if __name__ == "__main__":
    unittest.main()
