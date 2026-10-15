"""OpenMetrics shell contract and real emit/parse tests, not spec conformance.

Set OPENMETRICS_TEST_PYTHON to the installed implementation's venv interpreter
to exercise actual encoder/parser semantics, as in the native evidence replay.
"""

import os
import unittest

from test_vue_workflow import WorkflowShellMixin, WorkflowContractMixin, audit, ROOT


class OpenMetricsWorkflowTests(WorkflowContractMixin, unittest.TestCase):
    slug = "openmetrics"

    def test_format_version_is_distinct_from_implementation(self):
        self.assertEqual(self.job["outputs"]["package_name"], "OpenMetrics")
        for name in ("version", "test2"):
            for field in ("implementation_name", "implementation_version", "content_type"):
                self.assertTrue(audit._step_emits_output(ROOT, self.steps[name], field))
        self.assertIn('media.get_param("version")', self.steps["version"]["run"])
        self.assertIn('generate_latest(registry, version=wire_version)', self.steps["version"]["run"])


@unittest.skipUnless(os.environ.get("OPENMETRICS_TEST_PYTHON"), "Real client venv requires OPENMETRICS_TEST_PYTHON")
class OpenMetricsRuntimeTests(WorkflowShellMixin, unittest.TestCase):
    slug = "openmetrics"

    def real(self, name, **arguments):
        return self.run_step(name, OPENMETRICS_PYTHON=os.environ["OPENMETRICS_TEST_PYTHON"], **arguments)

    def baseline(self):
        result, fields = self.real("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fields["version"], "1.0.0")
        self.assertEqual(fields["implementation_name"], "prometheus-client")
        self.assertEqual(fields["content_type"], "application/openmetrics-text; version=1.0.0; charset=utf-8")
        values = self.values()
        values.update({f"steps.version.outputs.{key}": value for key, value in fields.items()})
        return values

    def test_real_format_identity_and_semantics(self):
        values = self.baseline()
        for name in ("test1", "test2", "test3", "test5"):
            result, fields = self.real(name, values=values)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fields["status"], "passed")

    def test_changed_format_or_implementation_fails(self):
        for field in ("version", "implementation_version"):
            values = self.baseline()
            values[f"steps.version.outputs.{field}"] = "9.9.9"
            for name in ("test2", "test5"):
                self.rejected(name, values=values, OPENMETRICS_PYTHON=os.environ["OPENMETRICS_TEST_PYTHON"])

    def test_legacy_prometheus_encoder_cannot_pass(self):
        values = self.baseline()
        before = "from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST, generate_latest"
        for name in ("version", "test2", "test5"):
            source = self.steps[name]["run"]
            self.assertIn(before, source)
            self.rejected(name, values=values, source=source.replace(before, "from prometheus_client import CONTENT_TYPE_LATEST, generate_latest"),
                          OPENMETRICS_PYTHON=os.environ["OPENMETRICS_TEST_PYTHON"])

    def test_real_metric_and_parser_mutations_fail(self):
        values = self.baseline()
        mutations = [("test5", "counter.labels(route).inc(3)", "counter.labels(route).inc(4)"),
                     ("test5", "gauge.dec()", "gauge.inc()"),
                     ("test5", "histogram.observe(0.75)", "histogram.observe(0.25)"),
                     ("test5", "parsed = list(text_string_to_metric_families(wire))", "wire = wire.removesuffix('# EOF\\n')\nparsed = list(text_string_to_metric_families(wire))"),
                     ("test5", "parsed = list(text_string_to_metric_families(wire))", "wire += 'arm_inflight 2\\n'\nparsed = list(text_string_to_metric_families(wire))"),
                     ("test3", 'valid.removesuffix("# EOF\\n")', "valid"),
                     ("test3", "list(text_string_to_metric_families(wire))", "list(text_string_to_metric_families(valid))")]
        for name, before, after in mutations:
            with self.subTest(step=name, mutation=before):
                source = self.steps[name]["run"]
                self.assertIn(before, source)
                self.rejected(name, values=values, source=source.replace(before, after),
                              OPENMETRICS_PYTHON=os.environ["OPENMETRICS_TEST_PYTHON"])


if __name__ == "__main__":
    unittest.main()
