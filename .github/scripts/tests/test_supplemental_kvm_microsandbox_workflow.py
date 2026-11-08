"""Policy and shell checks for the supplemental Microsandbox KVM lane."""

import hashlib
import re
import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/supplemental-kvm-microsandbox.yml"
HELPER = ROOT / ".github/scripts/tests/microsandbox_guest_smoke.sh"
CHECKOUT = "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
UPLOAD = "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"


class SupplementalKvmMicrosandboxTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text()
        self.doc = yaml.load(self.source, Loader=yaml.BaseLoader)
        self.jobs = self.doc["jobs"]
        self.guest = self.jobs["guest"]
        self.guest_steps = {step["name"]: step for step in self.guest["steps"]}

    def test_manual_protected_main_boundary(self):
        self.assertEqual(set(self.doc["on"]), {"workflow_dispatch"})
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertEqual(
            list(self.jobs), ["authorize", "provision", "guest", "cleanup"]
        )
        authorize = self.jobs["authorize"]
        self.assertEqual(authorize["runs-on"], "ubuntu-24.04-arm")
        boundary = authorize["steps"][0]["run"]
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', boundary)
        self.assertIn('test "$REF_PROTECTED" = "true"', boundary)
        self.assertEqual(
            authorize["steps"][0]["env"]["REF_PROTECTED"],
            "${{ github.ref_protected }}",
        )
        self.assertIn('test "$GITHUB_SHA" = "$CURRENT_MAIN_SHA"', boundary)
        self.assertIn('test "$CONFIRMATION" = "RUN-MICROSANDBOX-KVM"', boundary)
        self.assertIn("ORIGINAL_ACTOR", authorize["steps"][0]["env"])
        self.assertIn("TRIGGERING_ACTOR", authorize["steps"][0]["env"])
        self.assertNotIn("pull_request", self.doc["on"])
        self.assertNotIn("schedule", self.doc["on"])

    def test_provision_and_cleanup_use_foundation_actions_and_environments(self):
        provision = self.jobs["provision"]
        self.assertEqual(provision["environment"], "kvm-runner-provision")
        self.assertEqual(
            provision["permissions"], {"contents": "read", "id-token": "write"}
        )
        self.assertEqual(provision["steps"][0]["uses"], CHECKOUT)
        self.assertEqual(
            provision["steps"][0]["with"]["persist-credentials"], "false"
        )
        self.assertEqual(
            provision["steps"][1]["uses"],
            "./.github/actions/provision-ephemeral-kvm-runner",
        )
        self.assertIn("repository-read-token", provision["steps"][1]["with"])

        cleanup = self.jobs["cleanup"]
        self.assertEqual(cleanup["environment"], "kvm-runner-cleanup")
        self.assertEqual(
            cleanup["permissions"], {"contents": "read", "id-token": "write"}
        )
        self.assertIn("always()", cleanup["if"])
        self.assertEqual(set(cleanup["needs"]), {"provision", "guest"})
        self.assertEqual(cleanup["steps"][0]["uses"], CHECKOUT)
        self.assertEqual(
            cleanup["steps"][1]["uses"],
            "./.github/actions/cleanup-ephemeral-kvm-runner",
        )
        cleanup_inputs = cleanup["steps"][1]["with"]
        for name in (
            "instance-id",
            "ownership-nonce",
            "source-run-id",
            "source-run-attempt",
            "runner-name",
        ):
            self.assertIn(name, cleanup_inputs)

    def test_target_selects_only_dedicated_group_and_random_label(self):
        self.assertEqual(self.guest["permissions"], {})
        self.assertEqual(
            self.guest["runs-on"],
            {
                "group": "${{ vars.ECOSYSTEM_KVM_RUNNER_GROUP_NAME }}",
                "labels": "${{ needs.provision.outputs.runner-label }}",
            },
        )
        serialized = yaml.safe_dump(self.guest)
        self.assertNotIn("github.token", serialized)
        self.assertNotIn("secrets.", serialized)
        self.assertNotIn("id-token", serialized)
        self.assertNotIn("self-hosted", serialized)
        self.assertFalse(any(step.get("uses") == CHECKOUT for step in self.guest["steps"]))
        for step in self.guest["steps"]:
            self.assertNotIn("continue-on-error", step)

    def test_target_fetches_exact_public_source_without_repository_token(self):
        step = self.guest_steps["Fetch exact public source helper and pinned runtime"]
        script = step["run"]
        helper_sha256 = hashlib.sha256(HELPER.read_bytes()).hexdigest()
        self.assertIn(
            '"https://github.com/$GITHUB_REPOSITORY/archive/$GITHUB_SHA.tar.gz"',
            script,
        )
        self.assertIn("EXPECTED_HELPER_SHA256", self.guest["env"])
        self.assertEqual(
            self.guest["env"]["EXPECTED_HELPER_SHA256"], helper_sha256
        )
        self.assertIn("sha256sum --check --strict", script)
        self.assertIn("microsandbox_guest_smoke.sh", script)
        self.assertNotIn("Authorization:", script)
        self.assertNotIn("GH_TOKEN", script)
        self.assertNotIn("GITHUB_TOKEN", script)

    def test_target_requires_real_kvm_and_all_guest_behaviors(self):
        identity = self.guest_steps[
            "Verify runner identity, KVM and credential isolation"
        ]["run"]
        for requirement in (
            "test -c /dev/kvm",
            "test -r /dev/kvm",
            "test -w /dev/kvm",
            "fcntl.ioctl(device, 0xAE00, 0) != 12",
            "fcntl.ioctl(device, 0xAE01, 0)",
        ):
            self.assertIn(requirement, identity)
        for credential in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
            "ECOSYSTEM_KVM_RUNNER_APP_PRIVATE_KEY",
            "GITHUB_TOKEN",
        ):
            self.assertIn(credential, identity)

        mode_steps = {
            "Require healthy KVM and Microsandbox runtime prerequisites": "preflight",
            "Boot Arm64 guest and verify guest filesystem I/O": "guest",
            "Verify exact guest exit-status propagation": "exit-status",
            "Verify named guest lifecycle and subsequent exec": "lifecycle",
        }
        for name, mode in mode_steps.items():
            script = self.guest_steps[name]["run"]
            self.assertEqual(script, f'bash "$MICROSANDBOX_GUEST_HELPER" {mode}')
            self.assertNotIn("||", script)

        helper = HELPER.read_text()
        self.assertIn('test "$RC" -eq 23', helper)
        self.assertIn("grep -Fx MICROSANDBOX_ARM64_OK", helper)
        self.assertIn("grep -Fx MICROSANDBOX_LIFECYCLE_OK", helper)
        self.assertIn("failed to remove owned sandbox", helper)
        self.assertNotIn("skip", helper.lower())
        self.assertNotIn("|| true", helper)

    def test_evidence_is_supplemental_and_upload_is_pinned(self):
        upload = self.guest_steps["Preserve sanitized supplemental evidence"]
        self.assertEqual(upload["uses"], UPLOAD)
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        evidence = self.guest_steps["Write sanitized supplemental evidence"]["run"]
        self.assertIn('"scope": "supplemental_real_guest"', evidence)
        self.assertIn(
            '"guest_modes_passed": ["preflight", "guest", "exit-status", "lifecycle"]',
            evidence,
        )
        summary = self.guest_steps["Summarize supplemental validation"]["run"]
        self.assertIn("supplemental evidence only", summary)
        self.assertIn("recurring dashboard badge", summary)

    def test_all_embedded_shell_and_python_parse(self):
        for job in self.jobs.values():
            for step in job.get("steps", []):
                script = step.get("run")
                if script is None:
                    continue
                parsed = subprocess.run(
                    ["/bin/bash", "-n"], input=script, text=True, capture_output=True
                )
                self.assertEqual(parsed.returncode, 0, parsed.stderr)
                for source in re.findall(r"<<'PY'\n(.*?)\n\s*PY", script, re.S):
                    compile(source, str(WORKFLOW), "exec")


if __name__ == "__main__":
    unittest.main()
