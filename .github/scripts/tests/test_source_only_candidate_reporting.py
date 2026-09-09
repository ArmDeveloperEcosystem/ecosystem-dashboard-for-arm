"""Keep source/artifact-only candidate proof distinct from runtime installation."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
SLUGS = ("amazon-vpc-cni-k8s", "ampere-ai-text-to-sql", "cloud-native-stack",
         "cuda-python", "gluten", "ragflow", "wsl", "turbovnc")
SUMMARY_SLUGS = {"ragflow", "wsl", "turbovnc"}
SUMMARY_ACTION = "./.github/actions/write-package-job-summary"
INSTALLED_FIELD = "regression_next_installed_version"
LATEST_FIELD = "regression_latest_version"
LATEST_VALUE = "${{ steps.test6.outputs.latest_version || 'unknown' }}"


class SourceOnlyCandidateReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = {
            slug: yaml.safe_load((ROOT / ".github/workflows" / f"test-{slug}.yml").read_text())
            for slug in SLUGS
        }

    def job(self, slug):
        return self.workflows[slug]["jobs"][f"test-{slug}"]

    def summary_steps(self, slug):
        return [step for step in self.job(slug)["steps"]
                if step.get("uses") == SUMMARY_ACTION]

    def test_job_outputs_never_claim_candidate_installation(self):
        for slug in SLUGS:
            with self.subTest(slug=slug):
                self.assertEqual(self.job(slug)["outputs"][INSTALLED_FIELD], "not_installed")

    def test_workflow_call_keeps_forwarding_job_reporting(self):
        for slug in SLUGS:
            workflow = self.workflows[slug]
            # PyYAML's YAML 1.1 loader treats the unquoted `on` key as True.
            triggers = workflow.get("on", workflow.get(True))
            for field in (INSTALLED_FIELD, LATEST_FIELD):
                with self.subTest(slug=slug, field=field):
                    self.assertEqual(
                        triggers["workflow_call"]["outputs"][field]["value"],
                        "${{ jobs.test-" + slug + ".outputs." + field + " }}",
                    )

    def test_latest_candidate_identity_remains_available(self):
        for slug in SLUGS:
            with self.subTest(slug=slug):
                self.assertEqual(self.job(slug)["outputs"][LATEST_FIELD], LATEST_VALUE)

    def test_existing_summary_bindings_do_not_claim_installation(self):
        for slug in SLUGS:
            with self.subTest(slug=slug):
                summaries = self.summary_steps(slug)
                self.assertEqual(len(summaries), int(slug in SUMMARY_SLUGS))
                for step in summaries:
                    self.assertEqual(step["with"][INSTALLED_FIELD], "not_installed")

    def test_existing_summaries_keep_candidate_identity(self):
        for slug in sorted(SUMMARY_SLUGS):
            with self.subTest(slug=slug):
                summaries = self.summary_steps(slug)
                self.assertEqual(len(summaries), 1)
                self.assertEqual(summaries[0]["with"][LATEST_FIELD], LATEST_VALUE)


if __name__ == "__main__":
    unittest.main()
