"""Exercise EDOT version binding and smoke-shell failure accounting."""

import copy
import hashlib
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
sys.path.insert(0, str(ROOT / '.github/scripts'))
from package_observation_migration_audit import _step_emits_output, _step_literal_pairs
from package_result_policy import validate_publishable_result, validate_six_test_result


class PackageManagerDecisionChecks:
    """Shared EDOT/Robot checks execute the workflow and active collector verbatim."""

    def setUp(self):
        self.job = yaml.safe_load(self.workflow.read_text())['jobs']['test-' + self.slug]
        self.steps = {step['id']: step for step in self.job['steps'] if 'id' in step}
        self.temp = tempfile.TemporaryDirectory(prefix=self.slug + '-pm-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.executions = []
        self.values = {
            'steps.install.outcome': 'success',
            'steps.install.outputs.install_status': 'success',
            'steps.version.outcome': 'success',
            'steps.version.outputs.version': self.version,
            'steps.metadata.outputs.package_slug': self.slug,
            'steps.metadata.outputs.timestamp': '2026-09-09T00:00:00Z',
            'steps.metadata.outputs.dashboard_link': '/opensource_packages/' + self.slug,
            'github.run_id': '123', 'github.run_attempt': '1', 'github.job': 'test-' + self.slug,
        }
        for i in range(1, 6):
            self.values.update({f'steps.test{i}.outputs.status': 'passed',
                                f'steps.test{i}.outputs.duration': '2',
                                f'steps.test{i}.outcome': 'success',
                                f'steps.test{i}.conclusion': 'success'})

    def render(self, source):
        def expression(match):
            for term in match[1].split('||'):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    value = term[1:-1]
                elif term.isdigit():
                    value = term
                else:
                    self.assertRegex(term, r'^(steps|github)\.[\w.-]+$')
                    value = self.values.get(term, '')
                if value:
                    return value
            return ''
        return re.sub(r'\$\{\{\s*(.*?)\s*\}\}', expression, source)

    def run_pm_step(self, name):
        step = self.steps[name]
        output = self.root / 'output'
        output.write_text('')
        script = self.render(step['run'])
        environment = {key: self.render(value) for key, value in step.get('env', {}).items()}
        result = subprocess.run(
            ['bash', '-e', '-o', 'pipefail', '-c', script], cwd=self.root,
            env={**os.environ, **environment, 'GITHUB_OUTPUT': str(output)},
            text=True, capture_output=True, timeout=8,
        )
        lines = output.read_text().splitlines()
        fields = dict(line.split('=', 1) for line in lines)
        self.assertEqual(len(lines), len(fields), 'Duplicate terminal outputs')
        self.executions.append({'step': name, 'exit_code': result.returncode,
                                'source_sha256': hashlib.sha256(step['run'].encode()).hexdigest(),
                                'rendered_sha256': hashlib.sha256(script.encode()).hexdigest(),
                                'outputs': fields, 'stdout': result.stdout, 'stderr': result.stderr})
        self.values.update({f'steps.{name}.outputs.{key}': value for key, value in fields.items()})
        self.values[f'steps.{name}.outcome'] = 'success' if result.returncode == 0 else 'failure'
        return result, fields

    def decision_summary(self, decision):
        result, regression = self.run_pm_step('test6')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual((decision, 'skipped', '0'),
                         tuple(regression[key] for key in ('decision', 'status', 'duration')))
        return self.run_pm_step('summary')

    def assert_summary(self, result, summary, counts, duration='10'):
        passed, failed, skipped, core = counts
        self.assertEqual(1 if failed else 0, result.returncode, result.stderr)
        self.assertEqual({'passed': str(passed), 'failed': str(failed), 'skipped': str(skipped),
                          'core_failed': str(core), 'duration': duration,
                          'overall_status': 'failure' if failed else 'success',
                          'badge_status': 'failing' if failed else 'passing'}, summary)
        self.assertEqual(6, passed + failed + skipped)

    def collect(self, api_outcomes=None):
        """Use the collector's supported Jobs API fixture input, never repair its row."""
        outputs = {key: self.render(value) for key, value in self.job['outputs'].items()}
        job_name = 'test-' + self.slug
        job_url = 'https://github.com/fixture/pm/actions/runs/123/job/456'
        api_steps = []
        for i in range(1, 7):
            outcome = self.values.get(f'steps.test{i}.outcome', 'skipped')
            if api_outcomes and i in api_outcomes:
                outcome = api_outcomes[i]
            api_steps.append({'name': self.steps[f'test{i}']['name'], 'number': i,
                              'conclusion': outcome, 'started_at': '2026-09-09T00:00:00Z',
                              'completed_at': '2026-09-09T00:00:02Z'})
        status = self.values['steps.summary.outcome']
        needs = {job_name: {'result': status, 'outputs': outputs}}
        jobs = {'jobs': [{'name': job_name, 'html_url': job_url,
                          'conclusion': status, 'steps': api_steps}]}
        collector = yaml.safe_load((ROOT / '.github/actions/collect-batch-results/action.yml').read_text())
        script = collector['runs']['steps'][0]['run']
        with tempfile.TemporaryDirectory(prefix='collector-', dir=self.root) as directory:
            cwd = Path(directory)
            (cwd / '.github').mkdir()
            (cwd / '.github/scripts').symlink_to(ROOT / '.github/scripts', target_is_directory=True)
            (cwd / 'bin').mkdir()
            (cwd / 'bin/python3').symlink_to(sys.executable)
            result = subprocess.run(
                ['bash', '-e', '-o', 'pipefail', '-c', script], cwd=cwd,
                env={**os.environ, 'PATH': str(cwd / 'bin') + os.pathsep + os.environ['PATH'],
                     'NEEDS_JSON': json.dumps(needs), 'RUN_JOBS_JSON': json.dumps(jobs),
                     'BATCH_NUMBER': '1', 'BATCH_TITLE': 'Controlled PM fixture', 'GH_TOKEN': '',
                     'GITHUB_SERVER_URL': 'https://github.com', 'GITHUB_API_URL': 'https://api.github.com',
                     'GITHUB_REPOSITORY': 'fixture/pm', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                     'GITHUB_OUTPUT': str(cwd / 'output'), 'GITHUB_STEP_SUMMARY': str(cwd / 'summary'),
                     'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, text=True, timeout=10,
            )
            rows = list((cwd / 'test-results').rglob('*.json'))
            self.assertLessEqual(len(rows), 1)
            payload = json.loads(rows[0].read_text()) if rows else None
        self.executions.append({'step': 'collector', 'exit_code': result.returncode,
                                'source_sha256': hashlib.sha256(script.encode()).hexdigest(),
                                'needs': needs, 'jobs': jobs, 'payload': payload,
                                'stdout': result.stdout, 'stderr': result.stderr})
        return result, payload

    def assert_publishable(self, expected):
        result, payload = self.collect()
        self.assertEqual(0, result.returncode, result.stderr)
        tests, metadata = payload['tests'], payload['metadata']
        for key in ('passed', 'failed', 'skipped'):
            self.assertEqual(int(self.values[f'steps.summary.outputs.{key}']), tests[key])
        self.assertEqual(int(self.values['steps.summary.outputs.core_failed']), metadata['core_failed'])
        self.assertEqual(int(self.values['steps.summary.outputs.duration']), tests['duration_seconds'])
        self.assertEqual(self.values['steps.test6.outputs.decision'], tests['details'][5]['decision'])
        self.assertEqual(expected, validate_six_test_result(
            details=tests['details'], passed=tests['passed'], failed=tests['failed'],
            skipped=tests['skipped'], core_failed=metadata['core_failed'],
            decision=metadata['regression_decision']))
        self.assertEqual(expected, validate_publishable_result(payload))
        self.assertEqual('passing' if expected == 'success' else 'failing', metadata['badge_status'])
        return payload

    def test_actual_auditor_sees_all_three_literal_branches_and_summary_outputs(self):
        self.assertEqual('always()', self.steps['test6']['if'])
        self.assertEqual('always()', self.steps['summary']['if'])
        self.assertEqual({('baseline_install_failed', 'skipped'), ('baseline_failed', 'skipped'),
                          ('not_applicable_package_manager', 'skipped')},
                         set(_step_literal_pairs(ROOT, self.steps['test6'])))
        for step, fields in (('test6', ('decision', 'status', 'duration', 'current_version')),
                             ('summary', ('passed', 'failed', 'skipped', 'core_failed', 'duration',
                                          'overall_status', 'badge_status'))):
            for field in fields:
                self.assertTrue(_step_emits_output(ROOT, self.steps[step], field), (step, field))

    def test_positive_shell_collector_and_publisher(self):
        self.assert_summary(*self.decision_summary('not_applicable_package_manager'), (5, 0, 1, 0))
        self.assertEqual(self.version, self.values['steps.test6.outputs.current_version'])
        for field in ('latest_version', 'next_installed_version'):
            self.assertEqual('not_applicable', self.values[f'steps.test6.outputs.{field}'])
        self.assert_publishable('success')

    def test_each_failed_core_publishes_a_failed_baseline(self):
        original = dict(self.values)
        for i in range(1, 6):
            with self.subTest(test=i):
                self.values = dict(original)
                self.values.update({f'steps.test{i}.outputs.status': 'failed',
                                    f'steps.test{i}.outcome': 'failure'})
                self.assertEqual('success', self.values[f'steps.test{i}.conclusion'])
                self.assert_summary(*self.decision_summary('baseline_failed'), (4, 1, 1, 1))
                self.assert_publishable('failure')

    def test_masked_api_failure_is_rejected_without_a_row(self):
        self.values.update({'steps.test5.outputs.status': 'failed', 'steps.test5.outcome': 'failure'})
        self.assert_summary(*self.decision_summary('baseline_failed'), (4, 1, 1, 1))
        result, payload = self.collect({5: 'success'})
        self.assertNotEqual(0, result.returncode)
        self.assertIsNone(payload)
        self.assertIn('emitted failure counts contradict test details', result.stderr)

    def test_core_status_and_outcome_must_both_succeed(self):
        original = dict(self.values)
        for i in range(1, 6):
            for field, value in (('outputs.status', ''), ('outputs.status', 'failed'),
                                  ('outputs.status', 'skipped'), ('outputs.status', 'unknown'),
                                  ('outcome', ''), ('outcome', 'failure'),
                                  ('outcome', 'cancelled'), ('outcome', 'skipped')):
                with self.subTest(test=i, field=field, value=value):
                    self.values = dict(original)
                    self.values[f'steps.test{i}.{field}'] = value
                    self.assert_summary(*self.decision_summary('baseline_failed'), (4, 1, 1, 1))

    def test_install_failure_has_priority_and_cannot_coexist_with_a_green_baseline(self):
        original = dict(self.values)
        for field, value in (('outcome', ''), ('outcome', 'failure'), ('outcome', 'skipped'),
                              ('outcome', 'cancelled'), ('outputs.install_status', ''),
                              ('outputs.install_status', 'failed')):
            with self.subTest(field=field, value=value):
                self.values = dict(original)
                self.values[f'steps.install.{field}'] = value
                self.assert_summary(*self.decision_summary('baseline_install_failed'), (5, 1, 0, 0))
                self.values['steps.version.outcome'] = 'failure'
                for i in range(1, 6):
                    self.values[f'steps.test{i}.outputs.status'] = 'failed'
                    self.values[f'steps.test{i}.outcome'] = 'failure'
                self.assert_summary(*self.decision_summary('baseline_install_failed'), (0, 5, 1, 5))
                self.assert_publishable('failure')
                self.values['steps.test6.outputs.decision'] = 'baseline_failed'
                self.assert_summary(*self.run_pm_step('summary'), (0, 6, 0, 5))

    def test_bad_version_or_outcome_is_a_baseline_failure(self):
        original = dict(self.values)
        cases = [('outcome', value) for value in ('', 'failure', 'skipped', 'cancelled')]
        cases += [('outputs.version', value) for value in
                  ('', 'unknown', 'Framework', 'Elastic.OpenTelemetry', 'not_applicable', '1', '1.2.3 garbage')]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.values = dict(original)
                self.values[f'steps.version.{field}'] = value
                self.assert_summary(*self.decision_summary('baseline_failed'), (5, 1, 0, 0))
                self.values.update({'steps.test2.outputs.status': 'failed', 'steps.test2.outcome': 'failure'})
                self.assert_summary(*self.decision_summary('baseline_failed'), (4, 1, 1, 1))
                self.assert_publishable('failure')

    def test_test6_status_decision_and_outcome_must_match_the_baseline(self):
        self.decision_summary('not_applicable_package_manager')
        original = dict(self.values)
        cases = [('outputs.status', value) for value in ('', 'passed', 'failed', 'unknown')]
        cases += [('outputs.decision', value) for value in ('', 'not_configured', 'baseline_failed',
                  'baseline_install_failed', 'runtime_validation_not_automated')]
        cases += [('outcome', value) for value in ('', 'failure', 'cancelled', 'skipped')]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.values = dict(original)
                self.values[f'steps.test6.{field}'] = value
                self.assert_summary(*self.run_pm_step('summary'), (5, 1, 0, 0))
        self.values = dict(original)
        self.values.update({'steps.test5.outputs.status': 'failed', 'steps.test5.outcome': 'failure'})
        for decision in ('not_applicable_package_manager', 'baseline_install_failed', 'not_configured'):
            self.values['steps.test6.outputs.decision'] = decision
            self.assert_summary(*self.run_pm_step('summary'), (4, 2, 0, 1))

    def test_failed_test6_never_reaches_a_green_publisher(self):
        self.decision_summary('not_applicable_package_manager')
        self.values['steps.test6.outcome'] = 'failure'
        self.assert_summary(*self.run_pm_step('summary'), (5, 1, 0, 0))
        result, payload = self.collect()
        self.assertNotEqual(0, result.returncode)
        self.assertIsNone(payload)
        self.assertIn('passing result contradicts failure evidence', result.stderr)

    def test_durations_are_bounded_decimal_values_and_missing_results_fail_closed(self):
        original = dict(self.values)
        for i in range(1, 7):
            for duration in ('', 'bad', '-1', '1.5', '1000000', '99999999999999999999'):
                with self.subTest(test=i, duration=duration):
                    self.values = dict(original)
                    if i < 6:
                        self.values[f'steps.test{i}.outputs.duration'] = duration
                        self.assert_summary(*self.decision_summary('baseline_failed'), (4, 1, 1, 1), '8')
                    else:
                        self.decision_summary('not_applicable_package_manager')
                        self.values['steps.test6.outputs.duration'] = duration
                        self.assert_summary(*self.run_pm_step('summary'), (5, 1, 0, 0))
        self.values = dict(original)
        self.values['steps.test2.outputs.duration'] = '08'
        self.decision_summary('not_applicable_package_manager')
        self.values['steps.test6.outputs.duration'] = '09'
        self.assert_summary(*self.run_pm_step('summary'), (5, 0, 1, 0), '25')
        self.values.clear()
        self.assert_summary(*self.run_pm_step('summary'), (0, 6, 0, 5), '0')


class EdotPackageManagerDecisionTests(PackageManagerDecisionChecks, unittest.TestCase):
    slug = 'edot-dotnet-sdk'
    version = '1.21.0'
    workflow = ROOT / '.github/workflows/test-edot-dotnet-sdk.yml'


class EdotDotnetWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        document = yaml.safe_load((ROOT / '.github/workflows/test-edot-dotnet-sdk.yml').read_text())
        cls.steps = {step.get('id'): step for step in document['jobs']['test-edot-dotnet-sdk']['steps']}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='edot-workflow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'TestApp' / 'obj').mkdir(parents=True)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.output = self.root / 'output'
        self.report = {
            'version': 1,
            'projects': [{'frameworks': [{'framework': 'net8.0', 'topLevelPackages': [
                {'id': 'Elastic.OpenTelemetry', 'requestedVersion': '1.21.0', 'resolvedVersion': '1.21.0'}
            ]}]}],
        }
        self.assets = {
            'libraries': {'Elastic.OpenTelemetry/1.21.0': {'type': 'package'}},
            'targets': {'net8.0': {'Elastic.OpenTelemetry/1.21.0': {
                'type': 'package', 'runtime': {'lib/net8.0/Elastic.OpenTelemetry.dll': {}}
            }}},
        }
        dotnet = self.bin / 'dotnet'
        dotnet.write_text('''#!/bin/bash
set -eu
if [ "$1" = list ]; then
  test "$*" = 'list package --format json --output-version 1'
  printf '%s\n' "$FIXTURE_REPORT"
  exit "${FIXTURE_REPORT_RC:-0}"
elif [ "$1" = build ]; then
  exit "${FIXTURE_BUILD_RC:-0}"
elif [ "$1" = run ]; then
  printf '%s\n' "${FIXTURE_RUNTIME_OUTPUT:-EDOT tracing smoke passed: 1 validated activity}"
  exit "${FIXTURE_RUNTIME_RC:-0}"
fi
exit 99
''')
        dotnet.chmod(0o755)
        timeout = self.bin / 'timeout'
        timeout.write_text('#!/bin/sh\nshift 2\nexec "$@"\n')
        timeout.chmod(0o755)

    def run_step(self, step, **env):
        self.output.write_text('')
        (self.root / 'TestApp' / 'obj' / 'project.assets.json').write_text(json.dumps(self.assets))
        result = subprocess.run(
            ['bash', '-e', '-o', 'pipefail', '-c', self.steps[step]['run']],
            cwd=self.root, env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
                                'GITHUB_OUTPUT': str(self.output),
                                'EXPECTED_EDOT_VERSION': '1.21.0',
                                'FIXTURE_REPORT': json.dumps(self.report), **env},
            capture_output=True, text=True, timeout=8,
        )
        fields = dict(line.split('=', 1) for line in self.output.read_text().splitlines())
        return result, fields

    def test_version_uses_resolved_structured_package_identity(self):
        result, fields = self.run_step('version')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({'version': '1.21.0'}, fields)
        self.assertNotEqual('Elastic.OpenTelemetry', fields['version'])

    def test_changed_core_outputs_remain_visible_to_the_real_auditor(self):
        for step in ('test2', 'test5'):
            for field in ('status', 'duration'):
                with self.subTest(step=step, field=field):
                    self.assertTrue(_step_emits_output(ROOT, self.steps[step], field))

    def test_version_rejects_missing_duplicate_wrong_and_placeholder_packages(self):
        base = copy.deepcopy(self.report)
        for mutation in ('missing', 'duplicate', 'wrong-id', 'placeholder', 'framework', 'schema'):
            with self.subTest(mutation=mutation):
                self.report = copy.deepcopy(base)
                framework = self.report['projects'][0]['frameworks'][0]
                package = framework['topLevelPackages'][0]
                if mutation == 'missing':
                    framework['topLevelPackages'] = []
                elif mutation == 'duplicate':
                    framework['topLevelPackages'].append(copy.deepcopy(package))
                elif mutation == 'wrong-id':
                    package['id'] = 'Elastic.OpenTelemetry.Extensions'
                elif mutation == 'placeholder':
                    package['resolvedVersion'] = 'Elastic.OpenTelemetry'
                elif mutation == 'framework':
                    framework['framework'] = 'net9.0'
                else:
                    self.report['version'] = 2
                result, fields = self.run_step('version')
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn('version', fields)

    def test_failed_or_malformed_package_report_never_emits_version(self):
        for env in ({'FIXTURE_REPORT_RC': '9'}, {'FIXTURE_REPORT': '{'}):
            with self.subTest(env=env):
                result, fields = self.run_step('version', **env)
                self.assertNotEqual(0, result.returncode)
                self.assertNotIn('version', fields)

    def test_version_check_binds_restored_runtime_package(self):
        result, fields = self.run_step('test2')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('passed', fields['status'])
        self.assertGreaterEqual(int(fields['duration']), 0)

    def test_restored_wrong_version_identity_or_missing_runtime_fails(self):
        original = copy.deepcopy(self.assets)
        for mutation in ('version', 'identity', 'runtime', 'framework', 'empty'):
            with self.subTest(mutation=mutation):
                self.assets = copy.deepcopy(original)
                if mutation == 'version':
                    self.assets['libraries'] = {'Elastic.OpenTelemetry/1.20.0': {'type': 'package'}}
                elif mutation == 'identity':
                    self.assets['libraries']['Elastic.OpenTelemetry/1.21.0']['type'] = 'project'
                elif mutation == 'runtime':
                    self.assets['targets']['net8.0']['Elastic.OpenTelemetry/1.21.0']['runtime'] = {}
                elif mutation == 'framework':
                    self.assets['targets'] = {'net9.0': {}}
                else:
                    self.assets = {}
                result, fields = self.run_step('test2')
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', fields['status'])
                self.assertGreaterEqual(int(fields['duration']), 0)

    def test_runtime_executes_edot_and_checks_recorded_activity(self):
        result, fields = self.run_step('test5')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('passed', fields['status'])
        code = (self.root / 'TestApp' / 'Program.cs').read_text()
        for required in ('WithElasticDefaults(options)', 'SkipOtlpExporter = true',
                         'SkipInstrumentationAssemblyScanning = true', 'span.Recorded',
                         'processor.Count != 1', 'activity.GetTagItem("smoke.answer")',
                         'Architecture.Arm64', 'AddProcessor(processor)'):
            self.assertIn(required, code)
        self.assertNotIn('Console.WriteLine("EDOT smoke test")', code)

    def test_build_failure_runtime_failure_and_old_placeholder_output_fail(self):
        for env in ({'FIXTURE_BUILD_RC': '1'}, {'FIXTURE_RUNTIME_RC': '7'},
                    {'FIXTURE_RUNTIME_OUTPUT': 'EDOT smoke test'}):
            with self.subTest(env=env):
                result, fields = self.run_step('test5', **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', fields['status'])
                self.assertGreaterEqual(int(fields['duration']), 0)


if __name__ == '__main__':
    unittest.main()
