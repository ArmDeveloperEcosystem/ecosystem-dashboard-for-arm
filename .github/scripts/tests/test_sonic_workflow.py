"""SONiC component shell/contract faults; synthetic fixtures are not Arm evidence."""

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from ipaddress import ip_address
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/test-sonic.yml'
sys.path.insert(0, str(ROOT / '.github/scripts'))
import package_result_policy as policy
import promote_package_results as publisher


class SonicWorkflowTests(unittest.TestCase):
    slug = 'sonic'

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='sonic-component-fixture-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.job = yaml.safe_load(WORKFLOW.read_text())['jobs']['test-sonic']
        self.steps = {s['id']: s for s in self.job['steps'] if 'id' in s}
        self.pins = json.loads(self.job['env']['SONIC_PINS'])
        self.version = self.component_version('baseline')
        self.candidate = self.component_version('candidate')
        self.executions = []
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('date', 'bash', 'mktemp'):
            (self.bin / name).symlink_to(shutil.which(name))
        (self.bin / 'python3').symlink_to(sys.executable)
        self.tool('timeout', 'shift 2\nexec "$@"\n')
        self.env = {**os.environ, **self.job['env'], 'PATH': str(self.bin),
                    'PYTHONDONTWRITEBYTECODE': '1', 'SONIC_ROOT': str(self.root / 'runtime'),
                    'SONIC_PYTHON': sys.executable, 'RUNNER_TEMP': str(self.root),
                    'GITHUB_ENV': str(self.root / 'github-env'),
                    'GITHUB_STEP_SUMMARY': str(self.root / 'github-summary')}
        self.values = {
            'steps.install.outcome': 'success', 'steps.install.outputs.install_status': 'success',
            'steps.version.outcome': 'success', 'steps.version.outputs.status': 'passed',
            'steps.version.outputs.version': self.version,
            'steps.metadata.outputs.package_slug': self.slug,
            'steps.metadata.outputs.dashboard_link': '/opensource_packages/sonic',
            'steps.metadata.outputs.timestamp': '2026-09-10T12:00:00Z',
            'github.run_id': '123', 'github.run_attempt': '1', 'github.job': 'test-sonic',
        }
        for i in range(1, 7):
            self.values.update({f'steps.test{i}.outputs.status': 'passed',
                                f'steps.test{i}.outputs.duration': '2',
                                f'steps.test{i}.outcome': 'success'})
        self.values.update({
            'steps.test6.outputs.decision': 'next_install_validated',
            'steps.test6.outputs.current_version': self.version,
            'steps.test6.outputs.latest_version': self.candidate,
            'steps.test6.outputs.next_installed_version': self.candidate,
            'steps.test6.outputs.regression_result': 'Controlled source-component contract fixture.',
            'steps.test6.outputs.comparison': 'Fixture only; no OS or native product evidence.',
        })

    def component_version(self, lane):
        pin = self.pins[lane]
        return 'config_samples@' + pin['release'] + '+' + pin['revision']

    def tool(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\nset -eu\n' + body)
        path.chmod(0o755)
        return str(path)

    def render(self, source):
        def expression(match):
            for term in match[1].split('||'):
                term = term.strip()
                value = term[1:-1] if term.startswith("'") else self.values.get(term, '')
                if value:
                    return str(value)
            return ''
        return re.sub(r'\$\{\{\s*(.*?)\s*\}\}', expression, source)

    def run_step(self, name, **overrides):
        step = self.steps[name]
        script = self.render(step['run'])
        output = self.root / 'output'
        output.write_text('')
        env = {**self.env, 'GITHUB_OUTPUT': str(output), **overrides}
        result = subprocess.run(['/bin/bash', '-e', '-o', 'pipefail', '-c', script],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=600)
        lines = output.read_text().splitlines()
        fields = dict(line.split('=', 1) for line in lines)
        self.assertEqual(len(lines), len(fields), 'Duplicate terminal output keys')
        self.values.update({f'steps.{name}.outputs.{key}': value for key, value in fields.items()})
        self.values[f'steps.{name}.outcome'] = 'success' if result.returncode == 0 else 'failure'
        github_env = Path(env['GITHUB_ENV'])
        if github_env.exists():
            self.env.update(dict(line.split('=', 1) for line in github_env.read_text().splitlines()))
        record = {'step': name, 'exit': result.returncode, 'outputs': fields,
                  'stdout': result.stdout, 'stderr': result.stderr,
                  'source': step['run'], 'rendered': script,
                  'workflow_sha256': hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()}
        self.executions.append(record)
        evidence = os.environ.get('SONIC_WORKFLOW_EVIDENCE')
        if evidence:
            folder = Path(evidence) / self._testMethodName
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f'{len(self.executions):03d}-{name}.json').write_text(json.dumps(record, indent=2))
        return result, fields

    def rejected(self, name, **env):
        result, outputs = self.run_step(name, **env)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual('failed', outputs.get('status'))
        self.assertRegex(outputs['duration'], r'^[0-9]+$')
        return outputs

    def fixture_module(self):
        """A deliberately incomplete module exercises only source identity rejection."""
        root = Path(self.env['SONIC_ROOT']) / 'baseline'
        root.mkdir(parents=True)
        source = b"def get_available_config():\n    return ['t1', 'l2', 'empty', 'l1', 'l3']\n"
        (root / 'config_samples.py').write_bytes(source)
        pins = copy.deepcopy(self.pins)
        pins['baseline']['sha256'] = hashlib.sha256(source).hexdigest()
        self.env['SONIC_PINS'] = json.dumps(pins)
        manifest = dict(pins['baseline'], repository='sonic-net/sonic-buildimage',
                        component='src/sonic-config-engine/config_samples.py',
                        installation_method='source-module')
        (root / 'source.json').write_text(json.dumps(manifest))
        return root, manifest

    def assert_publishable(self, expected, unknown=False):
        result, payload = self.collect()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(expected, policy.validate_publishable_result(payload))
        for key in ('passed', 'failed', 'skipped'):
            self.assertEqual(int(self.values['steps.summary.outputs.' + key]), payload['tests'][key])
        registration = dict(batch_title='Batch 1',
            workflow_path='.github/workflows/test-sonic.yml', run_id='123', run_attempt='1',
            job_name=payload['run']['job_name'],
            job_url='https://github.com/fixture/pm/actions/runs/123/job/456',
            job_conclusion=expected, job_started_at='2026-09-09T00:00:00Z',
            job_completed_at='2026-09-11T00:00:00Z', resolution_status='resolved')
        arguments = dict(expected_slug='sonic', expected_repository='fixture/pm',
            expected_registration=registration, publication_role='candidate', validation_policy='strict')
        if unknown:
            with self.assertRaisesRegex(publisher.PromotionError, 'package version must not be a placeholder'):
                publisher.validate_persisted_result(payload, **arguments)
        else:
            self.assertEqual(expected, publisher.validate_persisted_result(payload, **arguments))
        return payload

    def collect(self, api_outcomes=None):
        """Execute the unchanged collector using its Jobs API fixture input."""
        outputs = {key: self.render(value) for key, value in self.job['outputs'].items()}
        status = self.values['steps.summary.outcome']
        api_steps = [{'name': self.steps[f'test{i}']['name'], 'number': i,
                      'conclusion': (api_outcomes or {}).get(i, self.values[f'steps.test{i}.outcome']),
                      'started_at': '2026-09-10T12:00:00Z',
                      'completed_at': '2026-09-10T12:00:02Z'} for i in range(1, 7)]
        needs = {'test-sonic': {'result': status, 'outputs': outputs}}
        jobs = {'jobs': [{'id': 456, 'name': 'test-sonic / test-sonic', 'steps': api_steps, 'conclusion': status,
                         'html_url': 'https://github.com/fixture/pm/actions/runs/123/job/456'}]}
        collector = yaml.safe_load((ROOT / '.github/actions/collect-batch-results/action.yml').read_text())
        script = collector['runs']['steps'][0]['run']
        with tempfile.TemporaryDirectory(prefix='sonic-collector-', dir=self.root) as directory:
            cwd = Path(directory)
            (cwd / '.github').mkdir()
            (cwd / '.github/scripts').symlink_to(ROOT / '.github/scripts')
            (cwd / 'bin').mkdir()
            (cwd / 'bin/python3').symlink_to(sys.executable)
            env = dict(os.environ, PATH=str(cwd / 'bin') + os.pathsep + os.environ['PATH'],
                NEEDS_JSON=json.dumps(needs), RUN_JOBS_JSON=json.dumps(jobs), BATCH_NUMBER='1',
                BATCH_TITLE='Batch 1', GH_TOKEN='', GITHUB_SERVER_URL='https://github.com',
                GITHUB_API_URL='https://api.github.com', GITHUB_REPOSITORY='fixture/pm',
                GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1', GITHUB_OUTPUT=str(cwd / 'output'),
                GITHUB_STEP_SUMMARY=str(cwd / 'summary'), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run(['/bin/bash', '-e', '-o', 'pipefail', '-c', script],
                                    cwd=cwd, env=env, capture_output=True, text=True, timeout=20)
            rows = list((cwd / 'test-results').rglob('*.json'))
            self.assertLessEqual(len(rows), 1)
            payload = json.loads(rows[0].read_text()) if rows else None
        record = {'step': 'collector', 'exit': result.returncode, 'needs': needs, 'jobs': jobs,
                  'payload': payload, 'stdout': result.stdout, 'stderr': result.stderr,
                  'source_sha256': hashlib.sha256(script.encode()).hexdigest()}
        self.executions.append(record)
        evidence = os.environ.get('SONIC_WORKFLOW_EVIDENCE')
        if evidence:
            folder = Path(evidence) / self._testMethodName
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f'{len(self.executions):03d}-collector.json').write_text(json.dumps(record, indent=2))
        return result, payload

    def test_workflow_scope_and_shell_syntax(self):
        self.assertEqual('ubuntu-24.04-arm', self.job['runs-on'])
        self.assertIn('component', self.job['outputs']['package_name'])
        self.assertNotIn('not_applicable_package_manager', WORKFLOW.read_text())
        self.assertNotIn('sonic --', WORKFLOW.read_text())
        for step in self.job['steps']:
            if 'run' in step:
                result = subprocess.run(['/bin/bash', '-n'], input=self.render(step['run']),
                                        capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_identity_checks_exact_source_component_and_version(self):
        root, original = self.fixture_module()
        result, outputs = self.run_step('version')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(self.version, outputs['version'])
        for key, value in [('repository', 'other/sonic'), ('component', 'sonic-audio'),
                           ('release', '202006-20200712'), ('ref', 'refs/heads/master'), ('revision', '0' * 40),
                           ('sha256', '0' * 64), ('installation_method', 'pip')]:
            with self.subTest(key=key):
                (root / 'source.json').write_text(json.dumps({**original, key: value}))
                self.rejected('version')
        (root / 'source.json').write_text(json.dumps(original))
        self.values['steps.version.outcome'] = 'success'
        self.values['steps.version.outputs.status'] = 'passed'
        self.values['steps.version.outputs.version'] = self.candidate
        self.rejected('test2')

    def test_missing_modified_redirected_source_and_metadata_fail(self):
        root, manifest = self.fixture_module()
        (root / 'config_samples.py').write_text('raise RuntimeError("foreign source")\n')
        self.rejected('version')
        (root / 'config_samples.py').unlink()
        (root / 'config_samples.py').symlink_to(WORKFLOW)
        self.rejected('version')
        (root / 'config_samples.py').unlink()
        self.rejected('version')
        (root / 'source.json').write_text('{}')
        self.rejected('version')

    def test_import_only_fixture_cannot_pass_configuration_behavior(self):
        self.fixture_module()
        for name in ('test3', 'test4', 'test5'):
            self.rejected(name)

    def t1_fixture_outputs(self):
        """Controlled generator outputs for assertion tests, not upstream execution."""
        outputs = {}
        for count in (4, 130):
            data = {
                'DEVICE_METADATA': {'localhost': {'hostname': 'sonic', 'type': 'LeafRouter', 'bgp_asn': '65100'}},
                'LOOPBACK_INTERFACE': {'Loopback0|10.1.0.1/32': {}},
                'DEVICE_NEIGHBOR': {}, 'PORT': {}, 'INTERFACE': {}, 'BGP_NEIGHBOR': {},
                'FLEX_COUNTER_TABLE': {'ACL': {'FLEX_COUNTER_STATUS': 'disable',
                    'FLEX_COUNTER_DELAY_STATUS': 'true', 'POLL_INTERVAL': '10000'}},
            }
            for index in range(count):
                port = f'Ethernet{index * 4}'
                local = str(ip_address('10.0.0.0') + 2 * index)
                peer = str(ip_address(local) + 1)
                upper = index < count // 2
                ordinal = index + 1 if upper else index - count // 2 + 1
                data['PORT'][port] = {'admin_status': 'up', 'mtu': '9100'}
                data['INTERFACE'][f'{port}|{local}/31'] = {}
                data['BGP_NEIGHBOR'][peer] = {
                    'rrclient': 0, 'name': f'ARISTA{ordinal:02d}' + ('T2' if upper else 'T0'),
                    'local_addr': local, 'nhopself': 0, 'holdtime': '180',
                    'asn': '65200' if upper else str(64000 + ordinal), 'keepalive': '60',
                }
            outputs[count] = data
        return outputs

    def check_t1_fixture(self, outputs):
        tree = ast.parse(self.job['env']['SONIC_CHECK'])
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {'seed', 't1'}]
        self.assertEqual({'seed', 't1'}, {node.name for node in functions})

        def generate(data, mode):
            self.assertEqual('t1', mode)
            return copy.deepcopy(outputs[len(data['PORT'])])

        namespace = {'module': SimpleNamespace(generate_sample_config=generate), 'ip_address': ip_address}
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<actual-t1-checker>', 'exec'), namespace)
        return namespace['t1']()

    def compare_fixture_data(self, lane, result):
        tree = ast.parse(self.job['env']['SONIC_CHECK'])
        branch = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                      and ast.unparse(node.test) == "mode == 'all'")
        index = next(index for index, node in enumerate(branch.body)
                     if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == 'comparison' for target in node.targets))
        body = branch.body[index:index + 2]
        self.assertIsInstance(body[1], ast.If)
        namespace = {'Path': Path, 'os': SimpleNamespace(environ={'SONIC_ROOT': str(self.root)}),
                     'json': json, 'lane': lane, 'result': result}
        exec(compile(ast.Module(body=body, type_ignores=[]), '<actual-candidate-comparison>', 'exec'), namespace)

    def test_large_t1_configuration_rejects_each_malformed_field(self):
        valid = self.t1_fixture_outputs()
        checked = self.check_t1_fixture(valid)
        self.assertEqual(valid[4], checked['small'])
        self.assertEqual(valid[130], checked['large'])
        faults = [
            (('BGP_NEIGHBOR', '10.0.1.3', 'asn'), '0'),
            (('BGP_NEIGHBOR', '10.0.1.3', 'name'), 'INCORRECT-PEER'),
            (('BGP_NEIGHBOR', '10.0.1.3', 'holdtime'), '0'),
            (('BGP_NEIGHBOR', '10.0.1.3', 'keepalive'), '0'),
            (('BGP_NEIGHBOR', '10.0.1.3', 'local_addr'), '10.0.1.3'),
            (('BGP_NEIGHBOR', '10.0.1.3', 'rrclient'), 1),
            (('BGP_NEIGHBOR', '10.0.1.3', 'nhopself'), 1),
            (('PORT', 'Ethernet516', 'mtu'), '1'),
            (('PORT', 'Ethernet516', 'admin_status'), 'down'),
            (('DEVICE_METADATA', 'localhost', 'hostname'), 'wrong-host'),
            (('LOOPBACK_INTERFACE',), {}),
            (('DEVICE_NEIGHBOR',), {'unexpected': {}}),
        ]
        for path, value in faults:
            with self.subTest(path=path):
                candidate = copy.deepcopy(valid)
                target = candidate[130]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(AssertionError):
                    self.check_t1_fixture(candidate)
        for table, key in [('INTERFACE', 'Ethernet516|10.0.1.2/31'),
                           ('BGP_NEIGHBOR', '10.0.1.3'), ('PORT', 'Ethernet516')]:
            with self.subTest(missing=table):
                candidate = copy.deepcopy(valid)
                del candidate[130][table][key]
                with self.assertRaises(AssertionError):
                    self.check_t1_fixture(candidate)

    def test_candidate_only_large_data_enters_actual_regression_comparison(self):
        baseline = self.t1_fixture_outputs()
        expected = {'t1': self.check_t1_fixture(baseline)}
        self.compare_fixture_data('baseline', expected)
        self.compare_fixture_data('candidate', copy.deepcopy(expected))
        candidate = copy.deepcopy(baseline)
        candidate[130]['UNEXPECTED_CANDIDATE_TABLE'] = {'unvalidated': 'changed'}
        observed = {'t1': self.check_t1_fixture(candidate)}
        self.assertEqual(expected['t1']['small'], observed['t1']['small'])
        with self.assertRaisesRegex(AssertionError, 'Candidate configuration regression'):
            self.compare_fixture_data('candidate', observed)

    def test_failed_install_preserves_original_exit_and_failure_output(self):
        script = self.root / '.github/actions/apt-bootstrap/bootstrap.sh'
        script.parent.mkdir(parents=True)
        script.write_text('exit 42\n')
        result, fields = self.run_step('install')
        self.assertEqual(42, result.returncode)
        self.assertEqual('failed', fields['install_status'])
        self.assertRegex(fields['duration'], r'^[0-9]+$')

    def test_real_shell_command_failure_and_timeout_never_pass(self):
        for code in (1, 42, 124, 137):
            failed_python = self.tool('failed-python', f'exit {code}\n')
            for name in ('version', 'test1', 'test2', 'test3', 'test4', 'test5'):
                self.values['steps.version.outcome'] = 'success'
                self.values['steps.version.outputs.status'] = 'passed'
                self.rejected(name, SONIC_PYTHON=failed_python)

    def test_six_passing_source_tests_reach_unchanged_strict_publisher(self):
        result, summary = self.run_step('summary')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(('6', '0', '0', '0'), tuple(summary[k] for k in ('passed', 'failed', 'skipped', 'core_failed')))
        self.assert_publishable('success')

    def test_each_failed_core_reaches_unchanged_collector_and_strict_publisher(self):
        original = dict(self.values)
        for i in range(1, 6):
            self.values = dict(original)
            self.values[f'steps.test{i}.outputs.status'] = 'failed'
            self.values[f'steps.test{i}.outcome'] = 'failure'
            result, regression = self.run_step('test6')
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('baseline_failed', regression['decision'])
            result, summary = self.run_step('summary')
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(('4', '1', '1', '1'), tuple(summary[k] for k in ('passed', 'failed', 'skipped', 'core_failed')))
            self.assert_publishable('failure')
            result, payload = self.collect({i: 'success'})
            self.assertNotEqual(0, result.returncode)
            self.assertIsNone(payload)

    def test_failed_install_is_not_hidden_by_continue_on_error(self):
        self.values['steps.install.outcome'] = 'failure'
        self.values['steps.install.conclusion'] = 'success'
        self.values['steps.version.outputs.version'] = 'unknown'
        for i in range(1, 6):
            self.rejected('test' + str(i))
        result, regression = self.run_step('test6')
        self.assertEqual('baseline_install_failed', regression['decision'])
        result, summary = self.run_step('summary')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(('0', '5', '1', '5'), tuple(summary[k] for k in ('passed', 'failed', 'skipped', 'core_failed')))
        self.assert_publishable('failure', unknown=True)

    def test_invalid_test6_decisions_and_version_mismatches_are_rejected(self):
        original = dict(self.values)
        faults = [('outputs.decision', decision) for decision in (
            '', 'not_configured', 'not_applicable_package_manager', 'runtime_validation_not_automated',
            'baseline_failed', 'baseline_install_failed', 'next_regression_failed')]
        faults += [('outputs.status', s) for s in ('', 'skipped', 'failed')]
        faults += [('outcome', s) for s in ('', 'failure', 'cancelled', 'skipped')]
        faults += [('outputs.' + k, v) for k in ('current_version', 'latest_version', 'next_installed_version')
                   for v in ('', 'unknown', '1.0', 'sonic-audio@1.0')]
        faults += [('outputs.duration', d) for d in ('', '-1', 'bad', '1000000')]
        for field, value in faults:
            with self.subTest(field=field, value=value):
                self.values = dict(original)
                self.values['steps.test6.' + field] = value
                result, summary = self.run_step('summary')
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failing', summary['badge_status'])
                collected, payload = self.collect()
                if collected.returncode == 0:
                    self.assertEqual('failure', policy.validate_publishable_result(payload))
                else:
                    self.assertIsNone(payload)

    def test_invalid_core_outcomes_and_durations_do_not_manufacture_passes(self):
        original = dict(self.values)
        for i in range(1, 6):
            for field, value in [('outputs.status', ''), ('outputs.status', 'skipped'),
                                 ('outcome', 'failure'), ('outcome', 'cancelled'),
                                 ('outputs.duration', ''), ('outputs.duration', 'bad')]:
                self.values = dict(original)
                self.values[f'steps.test{i}.' + field] = value
                result, summary = self.run_step('summary')
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('1', summary['core_failed'])
                self.assertEqual(6, sum(int(summary[k]) for k in ('passed', 'failed', 'skipped')))

    def test_candidate_actual_shell_failure_is_applicable_failure(self):
        failed_python = self.tool('failed-python', 'exit 42\n')
        result, regression = self.run_step('test6', SONIC_PYTHON=failed_python)
        self.assertEqual(42, result.returncode)
        self.assertEqual('failed', regression['status'])
        self.assertEqual('next_regression_failed', regression['decision'])
        self.assertEqual('not_installed', regression['next_installed_version'])
        result, summary = self.run_step('summary')
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(('5', '1', '0', '0'), tuple(summary[k] for k in ('passed', 'failed', 'skipped', 'core_failed')))
        self.assert_publishable('failure')

    def test_candidate_stage_failures_preserve_actual_shell_outcomes(self):
        """Stage fixtures validate control flow, not installation/product support."""
        executable = self.tool('candidate-stage-fixture', '''
test "$1" = -I
test "$2" = -c
if [ "$3" = "$SONIC_SOURCE_INSTALL" ]; then
  test "$4" = candidate
  if [ "$FAULT" = install ]; then exit 42; fi
elif [ "$3" = "$SONIC_CHECK" ]; then
  if [ "$4" = baseline ]; then
    test "$5" = all
    printf '%s\\n' "$BASELINE_VERSION"
  elif [ "$5" = identity ]; then
    if [ "$FAULT" = identity ]; then exit 42; fi
    if [ "$FAULT" = mismatch ]; then
      echo 'wrong-component@1.0'
    else
      printf '%s\\n' "$CANDIDATE_VERSION"
    fi
  elif [ "$5" = all ]; then
    if [ "$FAULT" = comparison ]; then exit 42; fi
    if [ "$FAULT" = changed ]; then
      echo 'wrong-component@2.0'
    else
      printf '%s\\n' "$CANDIDATE_VERSION"
    fi
  else
    exit 99
  fi
else
  exit 99
fi
''')
        original = dict(self.values)
        for fault in ('none', 'install', 'identity', 'mismatch', 'comparison', 'changed'):
            with self.subTest(fault=fault):
                self.values = dict(original)
                result, regression = self.run_step('test6', SONIC_PYTHON=executable,
                    FAULT=fault, BASELINE_VERSION=self.version, CANDIDATE_VERSION=self.candidate)
                self.assertEqual('passed' if fault == 'none' else 'failed', regression['status'])
                self.assertEqual(0 if fault == 'none' else 1, int(result.returncode != 0))
                if fault in ('install', 'identity', 'comparison'):
                    self.assertEqual(42, result.returncode)
                if fault == 'install':
                    self.assertEqual('not_installed', regression['next_installed_version'])
                if fault == 'mismatch':
                    self.assertEqual('wrong-component@1.0', regression['next_installed_version'])
                if fault in ('comparison', 'changed'):
                    self.assertEqual(self.candidate, regression['next_installed_version'])
                result, summary = self.run_step('summary')
                self.assertEqual('success' if fault == 'none' else 'failure', summary['overall_status'])
                self.assert_publishable(summary['overall_status'])

    def test_source_download_and_digest_fail_before_installing_module(self):
        original_root = self.env['SONIC_ROOT']
        for failure in ('transport', 'digest'):
            root = Path(original_root) / failure
            root.mkdir(parents=True)
            wrapper = '''import io, os, urllib.request
def response(*args, **kwargs):
    if os.environ['FAULT'] == 'transport':
        raise OSError('controlled transport failure')
    return io.BytesIO(b'wrong source component')
urllib.request.urlopen = response
exec(compile(os.environ['SONIC_SOURCE_INSTALL'], '<actual-source-installer>', 'exec'))
'''
            result = subprocess.run([sys.executable, '-I', '-c', wrapper, 'candidate'],
                env={**self.env, 'FAULT': failure, 'SONIC_ROOT': str(root)},
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(0, result.returncode)
            self.assertIn('controlled transport failure' if failure == 'transport' else 'Source digest mismatch',
                          result.stderr)
            self.assertFalse((root / 'candidate/config_samples.py').exists())
            self.assertFalse((root / 'candidate/source.json').exists())


if __name__ == '__main__':
    unittest.main()
