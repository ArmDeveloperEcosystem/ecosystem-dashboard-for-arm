"""Replay Enroot workflow shells with bounded source/package failure fixtures."""

import hashlib
import json
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '.github/scripts'))

import package_observation_migration_audit as audit
import package_result_policy as policy


JOB = yaml.safe_load((ROOT / '.github/workflows/test-enroot.yml').read_text())['jobs']['test-enroot']
STEPS = {step['id']: step for step in JOB['steps'] if 'id' in step}


class EnrootWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='enroot-workflow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        (self.root / 'baseline-src/src').mkdir(parents=True)
        (self.root / 'baseline-src/README.md').write_text('ENROOT container sandbox\n')
        page = self.root / JOB['env']['PACKAGE_PAGE']
        page.parent.mkdir(parents=True)
        page.write_text('---\nsupported_minimum_version:\n    version_number: 2.1.0\nworks_on_arm: true\n---\n')
        self.env = dict(os.environ, **JOB['env'], RUNNER_TEMP=str(self.root),
                        GITHUB_OUTPUT=str(self.root / 'outputs'), CALLS=str(self.root / 'calls'))
        self.env['PATH'] = str(self.bin) + os.pathsep + os.environ['PATH']
        self.values = {'steps.install.outputs.install_mode': 'github_source',
                       'steps.install.outputs.install_status': 'success',
                       'steps.install.outputs.resolved_tag': 'v2.1.0'}
        self.values.update({f'steps.test{i}.{field}': value for i in range(1, 6) for field, value in (
            ('outputs.status', 'passed'), ('outcome', 'success'))})
        self.stub('uname', 'echo "${TEST_ARCH:-aarch64}"')
        self.stub('timeout', 'shift; exec "$@"')
        self.stub('file', 'echo "${TEST_ELF:-ELF 64-bit ARM aarch64}"')
        if sys.platform == 'darwin':
            self.stub('sha256sum', 'exec shasum -a 256 "$@"')
        self.stub('git', '''
if [ "$1" = -C ]; then shift 2; fi
case "$1" in
  clone)
    test "${FAIL_STAGE:-}" != clone
    [[ "$*" == *'--branch v2.1.0 '* ]]
    mkdir -p baseline-src ;;
  describe) echo "${TEST_TAG:-v2.1.0}" ;;
  rev-parse) echo source-commit ;;
  config) exit 0 ;;
  submodule)
    if [ "$2" = update ]; then test "${FAIL_STAGE:-}" != fetch; fi
    if [ "$2" = foreach ]; then test "${FAIL_STAGE:-}" != pin; fi ;;
  *) exit 1 ;;
esac
''')
        self.stub('make', '''
test "${FAIL_STAGE:-}" != build
test "$1" = -j2
PREFIX="${2#DESTDIR=}"
test "$3" = prefix=/usr
test "$4" = install
mkdir -p "$PREFIX/usr/bin"
cp "$MOCK_BINARY" "$PREFIX/usr/bin/enroot"
touch "$PREFIX/usr/bin/enroot-mount"
''')
        self.stub('mock-enroot', '''
if [ "${SOURCE_DIR:-}" = baseline-src ]; then version=2.1.0; else version=4.2.1; fi
case "$1" in
  version)
    test "${FAIL_STAGE:-}" != version
    if [ "${FAIL_STAGE:-}" != missing_version ]; then echo "${MOCK_VERSION-$version}"; fi ;;
  list)
    test "${FAIL_STAGE:-}" != list
    test -d "$ENROOT_DATA_PATH"
    test -d "$XDG_RUNTIME_DIR"
    if [ "${NONEMPTY_LIST:-0}" = 1 ]; then echo unexpected-container; fi ;;
  *) exit 1 ;;
esac
''')
        self.env['MOCK_BINARY'] = str(self.bin / 'mock-enroot')
        # Only intercept the installed absolute CLI path; the workflow shell is real Bash.
        self.stub('bash', '''
if [ "$1" = /usr/bin/enroot ]; then
  test "${FAIL_STAGE:-}" != missing_cli
  shift
  exec /bin/bash "$MOCK_BINARY" "$@"
fi
exec /bin/bash "$@"
''')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\nset -euo pipefail\n'
                        'printf "%s %s\\n" "${0##*/}" "$*" >> "$CALLS"\n' + body + '\n')
        path.chmod(0o755)

    def candidate_fixture(self):
        self.artifact = self.root / 'artifact.deb'
        self.artifact.write_bytes(b'Enroot package fixture\n')
        digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.env['CANDIDATE_SHA256'] = digest
        self.release = self.root / 'release.json'
        self.release.write_text(json.dumps({
            'tag_name': 'v4.2.1', 'draft': False, 'prerelease': False,
            'assets': [{'name': 'enroot_4.2.1-1_arm64.deb', 'digest': f'sha256:{digest}',
                        'browser_download_url': 'https://github.com/NVIDIA/enroot/releases/download/v4.2.1/enroot_4.2.1-1_arm64.deb'}],
        }))
        self.env.update(FIXTURE_RELEASE=str(self.release), FIXTURE_ARTIFACT=str(self.artifact))
        self.stub('curl', '''
source="$FIXTURE_ARTIFACT"
while [ "$#" -gt 0 ]; do
  case "$1" in
    https://api.github.com/*)
      if [ "${FAIL_STAGE:-}" = release_fetch ]; then exit 22; fi
      source="$FIXTURE_RELEASE" ;;
    https://github.com/*)
      if [ "${FAIL_STAGE:-}" = artifact_fetch ]; then exit 22; fi ;;
    -o) shift; target="$1" ;;
  esac
  shift
done
cp "$source" "$target"
''')
        self.stub('dpkg-deb', '''
test "${FAIL_STAGE:-}" != archive
case "$3" in
  Package) echo "${MOCK_PACKAGE-enroot}" ;;
  Version) echo "${MOCK_PACKAGE_VERSION-4.2.1-1}" ;;
  Architecture) echo "${MOCK_PACKAGE_ARCH-arm64}" ;;
  *) exit 1 ;;
esac
''')
        self.stub('sudo', 'exec "$@"')
        self.stub('apt-get', '''
if [ "${FAIL_STAGE:-}" = install ]; then exit 17; fi
test "$1" = install
''')
        self.stub('dpkg-query', 'echo "${MOCK_INSTALLED_PACKAGE-install ok installed 4.2.1-1 arm64}"')

    def run_step(self, step, values=None, suffix='', **env):
        values = dict(self.values, **(values or {}))

        def expression(match):
            for term in match[1].split('||'):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else values.get(term, '')
                if value:
                    return value
            return ''

        output = Path(self.env['GITHUB_OUTPUT'])
        output.write_text('')
        (self.root / 'calls').write_text('')
        result = subprocess.run(['/bin/bash', '-e', '-o', 'pipefail', '-c',
                                 re.sub(r'\$\{\{\s*(.*?)\s*\}\}', expression, STEPS[step]['run']) + suffix],
                                cwd=self.root, env=dict(self.env, **env), capture_output=True,
                                text=True, timeout=20)
        outputs = dict(line.split('=', 1) for line in output.read_text().splitlines() if '=' in line)
        if step.startswith('test'):
            self.assertRegex(outputs['duration'], r'^\d+$')
        if step == 'test6':
            decision = outputs['decision']
            if decision in policy.PASSED_REGRESSION_DECISIONS:
                self.assertEqual('passed', outputs['status'])
                self.assertEqual(0, result.returncode)
            elif decision in policy.BASELINE_REGRESSION_DECISIONS:
                self.assertEqual('skipped', outputs['status'])
                self.assertEqual(0, result.returncode)
            else:
                self.assertIn(decision, policy.FAILED_REGRESSION_DECISIONS)
                self.assertEqual('failed', outputs['status'])
                self.assertNotEqual(0, result.returncode)
        return result, outputs

    def test_unchanged_auditor_sees_all_outputs_and_approved_decision_status_pairs(self):
        for number in range(1, 7):
            for output in ('status', 'duration'):
                with self.subTest(number=number, output=output):
                    self.assertTrue(audit._step_emits_output(ROOT, STEPS[f'test{number}'], output))
        self.assertEqual({'baseline_failed', 'next_install_failed', 'limited_cpu_smoke_failed', 'limited_cpu_smoke_validated'},
                         set(audit._step_literal_outputs(ROOT, STEPS['test6'], 'decision')))
        pairs = audit._step_literal_pairs(ROOT, STEPS['test6'])
        self.assertTrue(pairs)
        for decision, status in pairs:
            with self.subTest(decision=decision, status=status):
                expected = 'skipped' if decision in policy.BASELINE_REGRESSION_DECISIONS else policy.decision_group(decision)
                self.assertEqual(expected, status)

    def test_initial_outputs_survive_failure_before_exit_trap(self):
        self.stub('date', 'exit 31')
        for number in range(1, 7):
            with self.subTest(number=number):
                result, outputs = self.run_step(f'test{number}')
                self.assertEqual(31, result.returncode)
                self.assertEqual(('failed', '0'), tuple(outputs[key] for key in ('status', 'duration')))

    def test_candidate_requires_all_five_baseline_statuses_and_outcomes(self):
        self.candidate_fixture()
        for number in range(1, 6):
            for status, outcome in (('', 'success'), ('failed', 'success'), ('skipped', 'success'),
                                    ('passed', ''), ('passed', 'failure'), ('passed', 'skipped'),
                                    ('passed', 'cancelled')):
                with self.subTest(number=number, status=status, outcome=outcome):
                    values = self.success_values()
                    values.update({f'steps.test{number}.outputs.status': status,
                                   f'steps.test{number}.outcome': outcome,
                                   f'steps.test{number}.conclusion': 'success'})
                    result, outputs = self.run_step('test6', values)
                    self.assertEqual(0, result.returncode)
                    self.assertEqual(('skipped', 'baseline_failed', 'not_installed'), tuple(outputs[key] for key in (
                        'status', 'decision', 'next_installed_version')))
                    calls = (self.root / 'calls').read_text()
                    self.assertNotIn('curl ', calls)
                    self.assertNotIn('apt-get ', calls)
                    self.assertEqual([], list(self.root.glob('enroot-candidate.*')))
                    values.update({'steps.test6.outputs.status': outputs['status'],
                                   'steps.test6.outputs.decision': outputs['decision'], 'steps.test6.outcome': 'success'})
                    summary, counts = self.run_step('summary', values)
                    self.assertNotEqual(0, summary.returncode)
                    self.assertEqual(('4', '1', '1', '1', 'failure'), tuple(counts[key] for key in (
                        'passed', 'failed', 'skipped', 'core_failed', 'overall_status')))
                    details = [{'name': f'Test {i}', 'status': 'failed' if i == number else 'passed'} for i in range(1, 6)]
                    details.append({'name': 'Test 6', 'status': outputs['status'], 'decision': outputs['decision']})
                    self.assertEqual('failure', policy.validate_six_test_result(
                        details=details, decision=outputs['decision'],
                        **{key: int(counts[key]) for key in ('passed', 'failed', 'skipped', 'core_failed')}))

    def test_baseline_skip_requires_successful_explanation_step(self):
        for outcome in ('failure', 'cancelled', 'skipped', ''):
            with self.subTest(outcome=outcome):
                values = self.success_values()
                values.update({'steps.test5.outputs.status': 'failed', 'steps.test5.outcome': 'failure',
                               'steps.test6.outputs.status': 'skipped', 'steps.test6.outputs.decision': 'baseline_failed',
                               'steps.test6.outcome': outcome})
                summary, counts = self.run_step('summary', values)
                self.assertNotEqual(0, summary.returncode)
                self.assertEqual(('4', '2', '0', '1', 'failure'), tuple(counts[key] for key in (
                    'passed', 'failed', 'skipped', 'core_failed', 'overall_status')))

    def collect_actual_results(self, regression, counts, api_steps):
        action = yaml.safe_load((ROOT / '.github/actions/collect-batch-results/action.yml').read_text())
        source = action['runs']['steps'][0]['run'].split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        outputs = {
            'contract_version': '2.0', 'package_slug': 'enroot', 'package_name': 'NVIDIA Enroot',
            'package_version': JOB['env']['BASELINE_VERSION'], 'job_name': 'test-enroot',
            'run_status': counts['overall_status'], 'core_failed': counts['core_failed'],
            'tests_passed': counts['passed'], 'tests_failed': counts['failed'], 'tests_skipped': counts['skipped'],
            'duration_seconds': counts['duration'],
            **{f'regression_{key}': regression[key] for key in (
                'status', 'decision', 'current_version', 'latest_version', 'next_installed_version')},
            'regression_result': regression['regression_result'], 'regression_comparison': regression['comparison'],
        }
        job = {'id': 456, 'name': 'test-enroot / test-enroot', 'conclusion': counts['overall_status'],
               'html_url': 'https://github.com/example/project/actions/runs/123/job/456', 'steps': api_steps}
        with tempfile.TemporaryDirectory(prefix='enroot-collector-') as temporary:
            root = Path(temporary)
            (root / '.github').mkdir()
            (root / '.github/scripts').symlink_to(ROOT / '.github/scripts')
            environment = dict(os.environ, NEEDS_JSON=json.dumps({'test-enroot': {
                'result': counts['overall_status'], 'outputs': outputs}}), RUN_JOBS_JSON=json.dumps({'jobs': [job]}),
                BATCH_NUMBER='1', BATCH_TITLE='Batch 1', GH_TOKEN='', GITHUB_SERVER_URL='https://github.com',
                GITHUB_API_URL='https://api.github.com', GITHUB_REPOSITORY='example/project',
                GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', GITHUB_OUTPUT=str(root / 'outputs'),
                GITHUB_STEP_SUMMARY=str(root / 'summary'))
            result = subprocess.run([sys.executable, '-B', '-c', source], cwd=root, env=environment,
                                    capture_output=True, text=True, timeout=30)
            artifact = root / 'test-results/enroot-test-results/enroot.json'
            return result, json.loads(artifact.read_text()) if artifact.exists() else None

    def test_active_collector_accepts_baseline_guard_and_rejects_failed_api_conclusion(self):
        values = self.success_values()
        api_steps = []
        for number in range(1, 7):
            step = f'test{number}'
            result, outputs = self.run_step(step, values, FAIL_STAGE='build' if number == 5 else '')
            values.update({f'steps.{step}.outputs.{key}': value for key, value in outputs.items()})
            values[f'steps.{step}.outcome'] = 'success' if result.returncode == 0 else 'failure'
            api_steps.append({'name': STEPS[step]['name'], 'number': number,
                              'conclusion': 'SUCCESS' if result.returncode == 0 else 'FAILURE'})
        self.assertEqual(0, result.returncode)
        self.assertEqual(('skipped', 'baseline_failed'), (outputs['status'], outputs['decision']))
        summary, counts = self.run_step('summary', values)
        self.assertEqual(1, summary.returncode)
        collected, payload = self.collect_actual_results(outputs, counts, api_steps)
        self.assertEqual(0, collected.returncode, collected.stderr)
        self.assertEqual(['passed'] * 4 + ['failed', 'skipped'],
                         [detail['status'] for detail in payload['tests']['details']])
        self.assertEqual('baseline_failed', payload['tests']['details'][5]['decision'])
        self.assertEqual((4, 1, 1), tuple(payload['tests'][key] for key in ('passed', 'failed', 'skipped')))
        self.assertEqual(1, payload['metadata']['core_failed'])
        self.assertEqual('failure', policy.validate_publishable_result(payload))
        api_steps[5]['conclusion'] = 'FAILURE'
        rejected, payload = self.collect_actual_results(outputs, counts, api_steps)
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn('emitted skipped count contradicts test details', rejected.stderr)
        self.assertIsNone(payload)

    def test_preserves_baseline_source_pins_and_exact_official_candidate(self):
        self.assertEqual('2.1.0', JOB['env']['BASELINE_VERSION'])
        self.assertEqual('4.2.1', JOB['env']['CANDIDATE_VERSION'])
        self.assertEqual('267018b335815a6b32a562915de1f3fad579f7c9d6748e98c62e7369b40be421', JOB['env']['CANDIDATE_SHA256'])
        script = JOB['env']['ENROOT_SMOKE']
        self.assertIn('https://git.hadrons.org/git/libbsd.git', script)
        self.assertIn('git submodule foreach \'test "$(git rev-parse HEAD)" = "$sha1"\'', script)
        self.assertNotIn('VERSION=', script)
        self.assertNotIn('default_branch', STEPS['install']['run'])
        self.assertNotIn('generic-source-regression-check', str(STEPS['test6']))

    def test_install_requires_exact_historical_tag_and_propagates_clone_failure(self):
        for env in ({'FAIL_STAGE': 'clone'}, {'TEST_TAG': 'v4.2.1'}, {}):
            with self.subTest(env=env):
                result, outputs = self.run_step('install', **env)
                self.assertEqual(not env, result.returncode == 0, result.stderr)
                self.assertEqual('failed' if env else 'success', outputs['install_status'])
                self.assertNotIn('default_branch', (self.root / 'calls').read_text())

    def test_core_evidence_and_failures_report_status_and_duration(self):
        for number in range(1, 5):
            with self.subTest(number=number):
                result, outputs = self.run_step(f'test{number}')
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('passed', outputs['status'])
                failure = {'steps.install.outputs.install_mode': ''} if number == 3 else {}
                result, outputs = self.run_step(f'test{number}', failure, PACKAGE_PAGE='missing-page')
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])
        for tag in ('', 'default_branch', 'v2.1.01', 'v4.2.1'):
            result, outputs = self.run_step('test2', {'steps.install.outputs.resolved_tag': tag})
            self.assertNotEqual(0, result.returncode)
            self.assertEqual('failed', outputs['status'])

    def test_baseline_dependencies_build_and_cli_failures(self):
        for stage in ('fetch', 'pin', 'build', 'version', 'missing_version', 'list', ''):
            with self.subTest(stage=stage):
                result, outputs = self.run_step('test5', FAIL_STAGE=stage)
                self.assertEqual(not stage, result.returncode == 0, result.stderr)
                self.assertEqual('failed' if stage else 'passed', outputs['status'])

    def test_baseline_metadata_checks_nested_minimum_version_exactly(self):
        page = self.root / JOB['env']['PACKAGE_PAGE']
        page.write_bytes((ROOT / JOB['env']['PACKAGE_PAGE']).read_bytes())
        result, outputs = self.run_step('test2')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('passed', outputs['status'])
        for version in ('2.1.01', '4.2.1', None):
            with self.subTest(version=version):
                page.write_text(yaml.safe_dump({'supported_minimum_version': {'version_number': version},
                                               'elsewhere': {'version_number': '2.1.0'}}))
                result, outputs = self.run_step('test2')
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])

    def test_baseline_rejects_wrong_architecture_tag_version_and_list(self):
        for env in ({'TEST_ARCH': 'x86_64'}, {'TEST_ELF': 'ELF x86-64'}, {'TEST_TAG': 'v2.0.0'},
                    {'MOCK_VERSION': '2.1.01'}, {'MOCK_VERSION': ''}, {'NONEMPTY_LIST': '1'}):
            with self.subTest(env=env):
                result, outputs = self.run_step('test5', **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])

    def test_candidate_installs_and_reports_actual_cli_version_and_scope(self):
        self.candidate_fixture()
        result, outputs = self.run_step('test6')
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual('passed', outputs['status'])
        self.assertEqual('4.2.1', outputs['next_installed_version'])
        self.assertEqual('2.1.0', outputs['current_version'])
        self.assertEqual('4.2.1', outputs['latest_version'])
        self.assertEqual('limited_cpu_smoke_validated', outputs['decision'])
        self.assertIn('Debian package', outputs['comparison'])
        self.assertIn('Candidate source compilation, container import/start, and GPU hooks are not tested', outputs['comparison'])
        self.assertIn('apt-get install ', (self.root / 'calls').read_text())
        self.assertEqual([], list(self.root.glob('enroot-candidate.*')))

    def test_candidate_download_install_and_runtime_failures_fail_summary(self):
        self.candidate_fixture()
        for stage in ('release_fetch', 'artifact_fetch', 'archive', 'install', 'missing_cli', 'version', 'missing_version', 'list'):
            with self.subTest(stage=stage):
                result, outputs = self.run_step('test6', FAIL_STAGE=stage)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])
                if stage in ('release_fetch', 'artifact_fetch', 'install'):
                    self.assertEqual(17 if stage == 'install' else 22, result.returncode)
                self.assertEqual('4.2.1' if stage == 'list' else 'unknown' if stage in ('missing_cli', 'version', 'missing_version') else 'not_installed', outputs['next_installed_version'])
                self.assertEqual([], list(self.root.glob('enroot-candidate.*')))
                values = self.success_values()
                values.update({'steps.test6.outputs.status': outputs['status'], 'steps.test6.outcome': 'failure'})
                summary, counts = self.run_step('summary', values)
                self.assertNotEqual(0, summary.returncode)
                self.assertEqual(('5', '1', '0', '0'), tuple(counts[key] for key in ('passed', 'failed', 'skipped', 'core_failed')))

    def test_candidate_initial_outputs_are_overwritten_by_measured_results(self):
        self.candidate_fixture()
        self.stub('date', '''
if [ -e "$RUNNER_TEMP/clock" ]; then echo 107; else touch "$RUNNER_TEMP/clock"; echo 100; fi
''')
        result, outputs = self.run_step('test6')
        self.assertEqual(0, result.returncode, result.stderr)
        raw = Path(self.env['GITHUB_OUTPUT']).read_text().splitlines()
        self.assertEqual(['status=failed', 'duration=0'], raw[:2])
        self.assertEqual(['duration=0', 'duration=7'], [line for line in raw if line.startswith('duration=')])
        self.assertEqual(('passed', 'limited_cpu_smoke_validated', '7'),
                         tuple(outputs[key] for key in ('status', 'decision', 'duration')))

    def test_candidate_failure_after_validation_keeps_outputs_coherent(self):
        self.candidate_fixture()
        self.stub('date', '''
if [ -e "$RUNNER_TEMP/clock" ]; then echo 107; else touch "$RUNNER_TEMP/clock"; echo 100; fi
''')
        for cleanup_failure in (False, True):
            with self.subTest(cleanup_failure=cleanup_failure):
                (self.root / 'clock').unlink(missing_ok=True)
                if cleanup_failure:
                    self.stub('rm', 'exit 23')
                result, outputs = self.run_step('test6', suffix='' if cleanup_failure else '\nexit 29\n')
                self.assertEqual(23 if cleanup_failure else 29, result.returncode)
                self.assertEqual(('failed', 'limited_cpu_smoke_failed', '7', '4.2.1'),
                                 tuple(outputs[key] for key in ('status', 'decision', 'duration', 'next_installed_version')))
                self.assertIn('mock-enroot list', (self.root / 'calls').read_text())
                self.assertEqual(cleanup_failure, bool(list(self.root.glob('enroot-candidate.*'))))
                raw = Path(self.env['GITHUB_OUTPUT']).read_text().splitlines()
                self.assertEqual(['status=failed', 'duration=0'], raw[:2])
                self.assertEqual(['duration=0', 'duration=7'], [line for line in raw if line.startswith('duration=')])
                self.assertTrue(outputs['regression_result'].endswith('failed'))
                values = self.success_values()
                values.update({'steps.test6.outputs.status': outputs['status'], 'steps.test6.outcome': 'failure'})
                summary, counts = self.run_step('summary', values)
                self.assertNotEqual(0, summary.returncode)
                self.assertEqual(('5', '1', '0', '0', 'failure'), tuple(counts[key] for key in (
                    'passed', 'failed', 'skipped', 'core_failed', 'overall_status')))

    def test_candidate_rejects_missing_or_mismatched_release_provenance_before_install(self):
        self.candidate_fixture()
        metadata = json.loads(self.release.read_text())
        variants = [{'tag_name': 'v4.2.0'}, {'tag_name': None}, {'draft': True}, {'prerelease': True}, {'assets': []}]
        for field, value in (('digest', 'sha256:' + '0' * 64), ('name', 'other.deb'), ('browser_download_url', 'https://example.com/other.deb')):
            variants.append({'assets': [{**metadata['assets'][0], field: value}]})
        for changed in variants:
            with self.subTest(changed=changed):
                self.release.write_text(json.dumps({**metadata, **changed}))
                result, outputs = self.run_step('test6')
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])
                self.assertEqual('not_installed', outputs['next_installed_version'])
                self.assertNotIn('apt-get ', (self.root / 'calls').read_text())

    def test_candidate_corrupt_artifact_fails_real_checksum_before_package_inspection(self):
        self.candidate_fixture()
        self.artifact.write_bytes(b'corrupted download\n')
        result, outputs = self.run_step('test6')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual('failed', outputs['status'])
        self.assertEqual('not_installed', outputs['next_installed_version'])
        self.assertNotIn('dpkg-deb ', (self.root / 'calls').read_text())
        self.assertNotIn('apt-get ', (self.root / 'calls').read_text())
        self.assertEqual([], list(self.root.glob('enroot-candidate.*')))

    def test_candidate_rejects_package_identity_architecture_and_runtime_mismatches(self):
        self.candidate_fixture()
        for env in ({'MOCK_PACKAGE': 'other'}, {'MOCK_PACKAGE_VERSION': '4.2.0-1'},
                    {'MOCK_PACKAGE_ARCH': 'amd64'}, {'MOCK_INSTALLED_PACKAGE': ''},
                    {'TEST_ARCH': 'x86_64'}, {'TEST_ELF': 'ELF x86-64'},
                    {'MOCK_VERSION': '4.2.0'}, {'MOCK_VERSION': '4.2.10'},
                    {'MOCK_VERSION': ''}, {'NONEMPTY_LIST': '1'}):
            with self.subTest(env=env):
                result, outputs = self.run_step('test6', **env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])
                if 'MOCK_VERSION' in env:
                    self.assertEqual(env['MOCK_VERSION'] or 'unknown', outputs['next_installed_version'])
                    self.assertNotIn('mock-enroot list', (self.root / 'calls').read_text())
                self.assertEqual([], list(self.root.glob('enroot-candidate.*')))

    def success_values(self):
        return {f'steps.test{i}.{field}': value for i in range(1, 7) for field, value in (
            ('outputs.status', 'passed'), ('outcome', 'success'), ('outputs.duration', str(i)))}

    def test_summary_requires_six_actual_successes_and_never_hides_skips(self):
        result, counts = self.run_step('summary', self.success_values())
        self.assertEqual(0, result.returncode)
        self.assertEqual(('6', '0', '0', '21'), tuple(counts[key] for key in ('passed', 'failed', 'skipped', 'duration')))
        for i in range(1, 7):
            for status, outcome in (('', 'failure'), ('skipped', 'success'), ('passed', 'failure'), ('failed', 'success'), ('passed', 'cancelled'), ('passed', ''), ('passed', 'skipped')):
                with self.subTest(test=i, status=status, outcome=outcome):
                    values = self.success_values()
                    values.update({f'steps.test{i}.outputs.status': status, f'steps.test{i}.outcome': outcome})
                    result, counts = self.run_step('summary', values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(('5', '1', '0', '1' if i < 6 else '0', 'failure'), tuple(counts[key] for key in ('passed', 'failed', 'skipped', 'core_failed', 'overall_status')))


if __name__ == '__main__':
    unittest.main()
