from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/generated-site-data-review.yml"
CI_WORKFLOW = ROOT / ".github/workflows/generated-data-publisher-foundation-ci.yml"
MAIN_WORKFLOW = ROOT / ".github/workflows/main.yml"
OPERATIONS = ROOT / ".github/GENERATED_SITE_DATA_REVIEW.md"


class GeneratedSiteDataReviewContractTests(unittest.TestCase):
    def test_review_workflow_is_manual_only_and_fail_closed(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        trigger = workflow.split("permissions:", maxsplit=1)[0]

        self.assertIn("  workflow_dispatch:\n", trigger)
        self.assertNotIn("pull_request", trigger)
        self.assertNotIn("push:", trigger)
        self.assertIn("GENERATED_SITE_DATA_REVIEW_ENABLED", workflow)
        self.assertIn('== "true"', workflow)
        self.assertIn("vars.GENERATED_SITE_DATA_REVIEW_ENABLED == 'true'", workflow)
        self.assertIn("Generated site data review is dormant", workflow)

    def test_every_job_is_read_only_by_default_and_arm64_only(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotRegex(workflow, r"(?m)^\s+contents:\s+write\s*$")
        runners = re.findall(r"^\s+runs-on:\s*(\S+)\s*$", workflow, re.MULTILINE)
        self.assertEqual(runners, ["ubuntu-24.04-arm"] * 3)
        self.assertNotIn("self-hosted", workflow)
        self.assertNotIn("ubuntu-latest", workflow)

    def test_generation_runs_exact_existing_preprocessors_and_allowlist(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        commands = (
            "python3 ./build_steps/update_category_mappings.py",
            "python3 ./build_steps/update_recently_added_json.py",
            "python3 ./build_steps/validate_package_catagories.py",
        )
        for command in commands:
            self.assertEqual(workflow.count(command), 1)
        for path in (
            "data/category_data.yml",
            "data/category_data_windows.yml",
            "data/recently_added_packages.yaml",
        ):
            self.assertGreaterEqual(workflow.count(path), 2)
        self.assertIn("--base-sha", workflow)
        self.assertIn("archive_sha256", workflow)
        self.assertIn("retention-days: 1", workflow)
        self.assertIn('PYTHONDONTWRITEBYTECODE: "1"', workflow)
        self.assertIn("--require-hashes", workflow)
        self.assertIn("generated-site-data-requirements.txt", workflow)
        requirements = (
            ROOT / ".github/scripts/generated-site-data-requirements.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("PyYAML==6.0.3", requirements)
        self.assertIn(
            "10892704fc220243f5305762e276552a0395f7beb4dbf9b14ec8fd43b57f126c",
            requirements,
        )

    def test_generation_and_publication_are_separate_jobs(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(workflow, r"(?m)^  generate:\s*$")
        self.assertRegex(workflow, r"(?m)^  publish:\s*$")
        self.assertIn("environment: generated-data-delivery", workflow)
        restore = workflow.index("Validate and restore only allowlisted site data")
        mint = workflow.index("Mint short-lived Dashboard Delivery App token")
        reverify = workflow.index("Reverify exact bytes after credential minting")
        publish = workflow.index("Publish deterministic generated-data draft PR")
        self.assertLess(restore, mint)
        self.assertLess(mint, reverify)
        self.assertLess(reverify, publish)
        self.assertLess(
            workflow.index("Reject a missing or malformed App bot login"),
            mint,
        )

    def test_delivery_uses_only_the_scoped_app_contract(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertEqual(
            set(re.findall(r"secrets\.([A-Z0-9_]+)", workflow)),
            {"DASHBOARD_DELIVERY_APP_ID", "DASHBOARD_DELIVERY_APP_PRIVATE_KEY"},
        )
        for permission in (
            "permission-contents: write",
            "permission-metadata: read",
            "permission-pull-requests: write",
        ):
            self.assertIn(permission, workflow)
        self.assertNotIn("permission-workflows:", workflow)
        self.assertIn("credential-source: github-app", workflow)
        self.assertIn(
            "expected-pr-author-login: ${{ vars.DASHBOARD_DELIVERY_APP_BOT_LOGIN }}",
            workflow,
        )
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn(
            "github.token }}\n          permission-contents: write", workflow
        )

    def test_no_deploy_personal_token_or_base_branch_write_exists(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        lowered = workflow.lower()

        for forbidden in (
            "aws_access_key",
            "aws_secret",
            "hugo deploy",
            "production environment",
            "personal access token",
            "\n          pat:",
            "auto-merge",
            "git push origin main",
            "git push origin ${{ needs.activation.outputs.base_branch }}",
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertIn("draft PR", workflow)

    def test_all_external_actions_are_exactly_sha_pinned(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        external = []
        for line in workflow.splitlines():
            if "uses:" not in line:
                continue
            reference = (
                line.split("uses:", maxsplit=1)[1].split("#", maxsplit=1)[0].strip()
            )
            if reference.startswith("./"):
                continue
            external.append(reference)
        self.assertEqual(len(external), 6)
        for reference in external:
            _name, separator, revision = reference.rpartition("@")
            self.assertEqual(separator, "@")
            self.assertRegex(revision, r"^[0-9a-f]{40}$")

    def test_current_main_workflow_is_not_wired_to_the_dormant_path(self) -> None:
        main = MAIN_WORKFLOW.read_text(encoding="utf-8")

        self.assertNotIn("generated-site-data-review", main)
        self.assertNotIn("publish-generated-data-pr", main)
        self.assertIn("hugo deploy", main)

    def test_ci_is_read_only_arm64_and_covers_all_new_files(self) -> None:
        ci = CI_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("permissions:\n  contents: read", ci)
        self.assertNotIn("contents: write", ci)
        self.assertNotIn("secrets.", ci)
        self.assertIn("runs-on: ubuntu-24.04-arm", ci)
        self.assertIn(".github/scripts/tests", ci)
        self.assertIn("generated-site-data-review.yml", ci)
        self.assertIn("_linux_arm64.tar.gz", ci)
        self.assertIn(
            "325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6",
            ci,
        )

    def test_operations_documentation_declares_dormant_cutover_boundary(self) -> None:
        operations = OPERATIONS.read_text(encoding="utf-8")

        self.assertIn("dormant, manual-only", operations)
        self.assertIn("does not deploy", operations)
        self.assertIn("Missing configuration fails\nclosed", operations)
        self.assertIn("generated-data-delivery", operations)
        self.assertIn("DASHBOARD_DELIVERY_APP_ID", operations)
        self.assertIn("DASHBOARD_DELIVERY_APP_PRIVATE_KEY", operations)
        self.assertIn("DASHBOARD_DELIVERY_APP_BOT_LOGIN", operations)
        self.assertIn("downscopes its token", operations)
        self.assertIn("separately", operations)
        self.assertIn("Do not substitute a PAT", operations)


if __name__ == "__main__":
    unittest.main()
