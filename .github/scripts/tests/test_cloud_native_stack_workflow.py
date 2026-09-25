"""Exercise the real CNS config, Helm-result validation, and accounting scripts."""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
JOB = yaml.safe_load((ROOT / '.github/workflows/test-cloud-native-stack.yml').read_text())['jobs']['test-cloud-native-stack']
STEPS = {step['id']: step for step in JOB['steps'] if 'id' in step}


class CloudNativeStackWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cns-workflow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.baseline = self.root / 'baseline-src'
        self.candidate = self.root / 'candidate-fixture'
        self.baseline.mkdir()
        self.candidate.mkdir()
        (self.candidate / 'README.md').write_text('Cloud Native Stack\n')
        self.baseline_config = self.baseline / JOB['env']['BASELINE_CONFIG']
        self.candidate_config = self.candidate / 'playbooks/cns_values.yaml'
        self.config = {
            'cns_version': 8.0, 'helm_version': '3.10.0', 'gpu_operator_version': '22.9.0',
            'k8s_version': '1.25.2', 'gpu_driver_version': '520.61.07',
            'helm_repository': 'https://helm.ngc.nvidia.com/nvidia',
            'gpu_operator_helm_chart': 'nvidia/gpu-operator',
        }
        self.write_yaml(self.baseline_config, self.config)
        self.write_yaml(self.candidate_config, dict(self.config, cns_version=16.1, helm_version='4.0.4', gpu_operator_version='25.10.1', k8s_version='1.33.6'))
        self.render = self.root / 'render.yaml'
        self.documents = [dict(apiVersion='v1', kind=kind, metadata={'name': 'smoke-' + kind.lower()}) for kind in ('Deployment', 'DaemonSet', 'ServiceAccount', 'ClusterRole', 'CustomResourceDefinition', 'ClusterPolicy')]
        self.documents[0]['spec'] = {'template': {'spec': {'containers': [{'image': 'nvcr.io/nvidia/gpu-operator:v22.9.0'}]}}}
        self.render.write_text(yaml.safe_dump_all(self.documents))
        for name, version in (('baseline-chart', 'v22.9.0'), ('candidate-chart', 'v25.10.1')):
            self.write_yaml(self.root / name, {'name': 'gpu-operator', 'version': version, 'appVersion': version})
        self.env = dict(os.environ, **JOB['env'], RUNNER_TEMP=str(self.root), GITHUB_OUTPUT=str(self.root / 'outputs'), FIXTURE_NEXT=str(self.candidate), FIXTURES=str(self.root), TRACE=str(self.root / 'trace'))
        # Use this test interpreter's PyYAML on macOS; the workflow uses Ubuntu's apt-installed interpreter.
        self.env['CNS_HELM_SMOKE'] = self.env['CNS_HELM_SMOKE'].replace('/usr/bin/python3', shlex.quote(sys.executable))
        self.env['PATH'] = str(self.bin) + os.pathsep + os.environ['PATH']
        self.stub('uname', 'echo "${TEST_ARCH:-aarch64}"')
        self.stub('timeout', 'shift; exec "$@"')
        self.stub('file', 'echo "${TEST_ELF:-ELF 64-bit ARM aarch64}"')
        self.stub('sha256sum', 'test "${FAIL_STAGE:-}" != checksum')
        self.stub('git', '''
case "$1" in
  clone) test "${FAIL_STAGE:-}" != clone; cp -R "$FIXTURE_NEXT" next-src ;;
  describe) echo "${TEST_TAG:-v26.6.0}" ;;
  hash-object) echo "${CONFIG_BLOB:-blob}" ;;
  rev-parse)
    if [ "$2" != HEAD ]; then echo blob
    elif [[ "$PWD" = */next-src ]]; then echo "${SOURCE_COMMIT:-$CANDIDATE_SOURCE_COMMIT}"
    else echo "${SOURCE_COMMIT:-$BASELINE_SOURCE_COMMIT}"; fi ;;
  *) exit 1 ;;
esac
''')
        self.stub('curl', '''
printf 'curl %s\\n' "$*" >> "$TRACE"
test "${FAIL_STAGE:-}" != download
while [ "$1" != -o ]; do shift; done
touch "$2"
''')
        self.stub('tar', '''
test "$1" = -xzf
test "$3" = -C
mkdir -p "$4/linux-arm64"
cp "$FIXTURES/bin/helm-fixture" "$4/linux-arm64/helm"
''')
        self.stub('helm-fixture', '''
printf 'helm %s\\n' "$*" >> "$TRACE"
if [[ "$PWD" = */next-src ]]; then version=4.0.4; chart=candidate-chart; else version=3.10.0; chart=baseline-chart; fi
case "$1" in
  version) echo "v${HELM_VERSION_OVERRIDE:-$version}+fixture" ;;
  pull)
    test "${FAIL_STAGE:-}" != pull
    while [ "$1" != --untardir ]; do shift; done
    mkdir -p "$2/gpu-operator"
    cp "$FIXTURES/$chart" "$2/gpu-operator/Chart.yaml" ;;
  template)
    test "${FAIL_STAGE:-}" != render
    cat "$FIXTURES/render.yaml" ;;
  *) echo 'Only version, pull, and template are allowed' >&2; exit 99 ;;
esac
''')

    def write_yaml(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value))

    def stub(self, name, body):
        target = self.bin / name
        target.write_text('#!/bin/bash\nset -euo pipefail\n' + body + '\n')
        target.chmod(0o755)

    def run_script(self, script, **env):
        output = Path(self.env['GITHUB_OUTPUT'])
        output.write_text('')
        result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=self.root, env=dict(self.env, **env), text=True, capture_output=True, timeout=30)
        return result, dict(line.split('=', 1) for line in output.read_text().splitlines() if '=' in line)

    def run_step(self, step, values=None, **env):
        values = values or {}
        def expression(match):
            terms = match[1].split('||')
            return values.get(terms[0].strip(), terms[-1].strip().strip("'") if len(terms) > 1 else '')
        script = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', expression, STEPS[step]['run'])
        return self.run_script(script, **env)

    def baseline_probe(self, **env):
        return self.run_step('test5', {'steps.install.outputs.install_mode': 'github_source'}, **env)

    def candidate_probe(self, **env):
        action = yaml.safe_load((ROOT / '.github/actions/generic-source-regression-check/action.yml').read_text())
        inputs = {key: value.get('default', '') for key, value in action['inputs'].items()}
        inputs.update(STEPS['test6']['with'])
        inputs.update(baseline_version='8.0', github_repo=JOB['env']['GITHUB_REPO'], lane_kind=JOB['env']['LANE_KIND'])
        def render(value):
            return re.sub(r'\$\{\{\s*inputs\.(\w+)\s*\}\}', lambda match: inputs[match[1]], value)
        step = action['runs']['steps'][0]
        return self.run_script(render(step['run']), **{**{key: render(value) for key, value in step['env'].items()}, **env})

    def test_real_render_command_uses_config_pins_and_preserves_release_identity(self):
        result, outputs = self.baseline_probe()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('passed', outputs['status'])
        trace = (self.root / 'trace').read_text()
        self.assertIn('--version v22.9.0', trace)
        self.assertIn('helm-v3.10.0-linux-arm64.tar.gz', trace)
        self.assertIn('--kube-version 1.25.2', trace)
        self.assertIn('driver.version=520.61.07', trace)
        self.assertIn('"images": ["nvcr.io/nvidia/gpu-operator:v22.9.0"]', result.stdout)
        result, outputs = self.candidate_probe()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('passed', outputs['status'])
        self.assertEqual(('8.0', '26.6.0', '26.6.0'), tuple(outputs[key] for key in ('current_version', 'latest_version', 'next_installed_version')))
        self.assertIn('cns=16.1', result.stdout)
        self.assertIn('--version v25.10.1', (self.root / 'trace').read_text())
        self.assertNotIn('default_branch', STEPS['install']['run'])
        self.assertNotIn('defer_on_limited_cpu_probe_failure', STEPS['test6']['with'])

    def test_wrong_config_version_repository_and_chart_are_rejected(self):
        for key, value in (('cns_version', 8.1), ('helm_repository', 'https://unrelated.invalid'), ('gpu_operator_helm_chart', 'unrelated/chart')):
            with self.subTest(key=key):
                self.write_yaml(self.baseline_config, dict(self.config, **{key: value}))
                result, outputs = self.baseline_probe()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])

    def test_config_provenance_architecture_and_helm_version_are_required(self):
        for env in ({'SOURCE_COMMIT': 'wrong'}, {'CONFIG_BLOB': 'dirty'}, {'TEST_ARCH': 'x86_64'}, {'TEST_ELF': 'ELF x86-64'}, {'HELM_VERSION_OVERRIDE': '3.15.4'}):
            with self.subTest(env=env):
                result, outputs = self.baseline_probe(**env)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])

    def test_download_checksum_pull_and_render_failures_remain_failures(self):
        for stage in ('download', 'checksum', 'pull', 'render'):
            with self.subTest(stage=stage):
                result, outputs = self.baseline_probe(FAIL_STAGE=stage)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])
                self.assertFalse(list(self.root.glob('cns-helm.*')))

    def test_downloaded_chart_name_and_versions_are_bound(self):
        for field, value in (('name', 'unrelated'), ('version', 'v22.9.1'), ('appVersion', 'v22.9.1')):
            with self.subTest(field=field):
                chart = dict(name='gpu-operator', version='v22.9.0', appVersion='v22.9.0')
                chart[field] = value
                self.write_yaml(self.root / 'baseline-chart', chart)
                result, outputs = self.baseline_probe()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])

    def test_render_must_be_valid_kubernetes_with_required_kinds_and_images(self):
        missing_images = json.loads(json.dumps(self.documents))
        del missing_images[0]['spec']
        for rendered in ('', 'not: [valid', yaml.safe_dump_all(self.documents[1:]), yaml.safe_dump_all(missing_images), 'kind: Deployment\nimage: text-only\n'):
            with self.subTest(rendered=rendered[:40]):
                self.render.write_text(rendered)
                result, outputs = self.baseline_probe()
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('failed', outputs['status'])

    def test_candidate_config_and_render_failures_propagate_through_composite_and_summary(self):
        for env in ({'CANDIDATE_CNS_VERSION': '19.0'}, {'FAIL_STAGE': 'render'}, {'TEST_TAG': 'v26.5.0'}, {}):
            with self.subTest(env=env):
                result, outputs = self.candidate_probe(**env)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('failed' if env else 'passed', outputs['status'])
                self.assertEqual('limited_cpu_smoke_failed' if env else 'limited_cpu_smoke_validated', outputs['decision'])
                values = self.success_values()
                values['steps.test6.outputs.status'] = outputs['status']
                summary, counts = self.run_step('summary', values)
                self.assertEqual(not env, summary.returncode == 0)
                self.assertEqual('1' if env else '0', counts['failed'])
                self.assertEqual('0', counts['core_failed'])

    def success_values(self):
        return {f'steps.test{i}.{field}': value for i in range(1, 7) for field, value in (('outputs.status', 'passed'), ('outcome', 'success'), ('outputs.duration', '1'))}

    def test_summary_requires_all_six_results_and_actual_outcomes(self):
        result, counts = self.run_step('summary', self.success_values())
        self.assertEqual(0, result.returncode)
        self.assertEqual(('6', '0', '0', '6'), tuple(counts[key] for key in ('passed', 'failed', 'skipped', 'duration')))
        for number in range(1, 7):
            for status, outcome in (('', 'failure'), ('skipped', 'success'), ('passed', 'failure'), ('passed', ''), ('failed', 'success')):
                with self.subTest(number=number, status=status, outcome=outcome):
                    values = self.success_values()
                    values.update({f'steps.test{number}.outputs.status': status, f'steps.test{number}.outcome': outcome})
                    result, counts = self.run_step('summary', values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(('5', '1', '0', '1' if number < 6 else '0'), tuple(counts[key] for key in ('passed', 'failed', 'skipped', 'core_failed')))


if __name__ == '__main__':
    unittest.main()
