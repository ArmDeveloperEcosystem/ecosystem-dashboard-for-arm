from __future__ import annotations

import re
import unittest
from collections import Counter
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
PROVISION = ROOT / ".github/actions/provision-ephemeral-kvm-runner/action.yml"
CLEANUP = ROOT / ".github/actions/cleanup-ephemeral-kvm-runner/action.yml"
WORKFLOW = ROOT / ".github/workflows/validate-ephemeral-kvm-runner.yml"
FOUNDATION_WORKFLOW = ROOT / ".github/workflows/ephemeral-kvm-runner-foundation-ci.yml"
TEMPLATE = ROOT / ".github/infrastructure/ecosystem-kvm-runner.yaml"
RUNBOOK = ROOT / ".github/EPHEMERAL_KVM_RUNNER.md"
CFN_REQUIREMENTS = ROOT / ".github/scripts/requirements-cfn-lint.txt"


class CloudFormationLoader(yaml.SafeLoader):
    pass


def cloudformation_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CloudFormationLoader.add_multi_constructor("!", cloudformation_tag)


class EphemeralKvmRunnerFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provision_text = PROVISION.read_text()
        cls.cleanup_text = CLEANUP.read_text()
        cls.workflow_text = WORKFLOW.read_text()
        cls.foundation_workflow_text = FOUNDATION_WORKFLOW.read_text()
        cls.template_text = TEMPLATE.read_text()
        cls.provision = yaml.safe_load(cls.provision_text)
        cls.cleanup = yaml.safe_load(cls.cleanup_text)
        cls.workflow = yaml.safe_load(cls.workflow_text)
        cls.template = yaml.load(cls.template_text, Loader=CloudFormationLoader)

    def test_metadata_is_structured_and_documented(self):
        self.assertEqual("composite", self.provision["runs"]["using"])
        self.assertEqual("composite", self.cleanup["runs"]["using"])
        self.assertTrue(RUNBOOK.is_file())

    def test_external_actions_are_full_sha_pinned(self):
        action_references = [
            reference
            for reference in re.findall(
                r"uses:\s+([^\s#]+)",
                self.provision_text
                + self.cleanup_text
                + self.workflow_text
                + self.foundation_workflow_text,
            )
            if not reference.startswith("./")
        ]
        self.assertEqual(
            Counter({
                "actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510": 2,
                "aws-actions/configure-aws-credentials@e1253824e5c10ff9df46874f81ed3ec929e19cfd": 2,
                "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803": 3,
                "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02": 1,
            }),
            Counter(action_references),
        )

    def test_provisioning_is_bound_to_protected_main_and_dedicated_group(self):
        self.assertIn('expected_repository="ArmDeveloperEcosystem/ecosystem-dashboard-for-arm"', self.provision_text)
        self.assertIn('[[ "$GITHUB_REF" == "refs/heads/main" ]]', self.provision_text)
        self.assertIn('test "$GITHUB_SHA" = "$current_main_sha"', self.provision_text)
        self.assertIn("(( RUNNER_GROUP_ID > 1 ))", self.provision_text)
        self.assertIn("secrets.token_hex(16)", self.provision_text)
        self.assertIn("labels: [$label]", self.provision_text)
        self.assertNotIn('labels: ["self-hosted"', self.provision_text)

    def test_dispatch_rejects_stale_commits_and_unauthorized_reruns(self):
        self.assertIn("ECOSYSTEM_KVM_ALLOWED_ACTORS_JSON", self.workflow_text)
        self.assertIn("github.triggering_actor", self.workflow_text)
        self.assertIn("github.actor", self.workflow_text)
        self.assertIn('test "$GITHUB_SHA" = "$current_main_sha"', self.workflow_text)

    def test_target_has_no_persistent_cloud_identity_or_inbound_path(self):
        self.assertNotIn("IamInstanceProfile", self.template_text)
        self.assertNotIn("KeyName", self.template_text)
        self.assertIn('"HttpEndpoint": "disabled"', self.template_text)
        self.assertIn('"InstanceMetadataTags": "disabled"', self.template_text)
        self.assertIn('InstanceInitiatedShutdownBehavior="terminate"', self.template_text)
        self.assertNotRegex(self.provision_text, r"set\s+-[^\n]*x")

    def test_bootstrap_and_aws_janitor_both_enforce_expiry(self):
        self.assertIn("systemd-run --unit=ecosystem-kvm-expiry", self.provision_text)
        self.assertIn("ExpiresAt", self.template_text)
        self.assertIn("KvmRunnerExpiryFunction", self.template["Resources"])
        self.assertIn("rate(5 minutes)", self.template_text)
        self.assertIn('get_paginator("describe_instances")', self.template_text)
        self.assertIn("Fail-closed expiry for malformed tag", self.template_text)
        self.assertIn("tagged_expiry.tzinfo is None", self.template_text)
        self.assertIn("except (TypeError, ValueError):", self.template_text)
        self.assertIn('instance["LaunchTime"] + datetime.timedelta(minutes=60)', self.template_text)
        self.assertIn("KvmRunnerMultiplicityAlarm", self.template["Resources"])
        self.assertIn("KvmRunnerJanitorErrorAlarm", self.template["Resources"])
        self.assertIn("KvmRunnerJanitorHeartbeatAlarm", self.template["Resources"])
        for name in (
            "KvmRunnerMultiplicityAlarm",
            "KvmRunnerJanitorErrorAlarm",
            "KvmRunnerJanitorHeartbeatAlarm",
        ):
            alarm = self.template["Resources"][name]["Properties"]
            self.assertEqual(["AlarmTopicArn"], alarm["AlarmActions"])
        janitor = self.template["Resources"]["KvmRunnerExpiryFunction"]["Properties"]["Code"]["ZipFile"]
        compile(janitor, "ecosystem-kvm-expiry.py", "exec")

    def test_cloudformation_creates_an_isolated_vpc(self):
        resources = self.template["Resources"]
        self.assertIn("KvmRunnerVpc", resources)
        self.assertIn("KvmRunnerSubnet", resources)
        self.assertIn("KvmRunnerInternetGateway", resources)
        self.assertNotIn("VpcId", self.template["Parameters"])
        self.assertNotIn("SubnetId", self.template["Parameters"])
        security_group = resources["KvmRunnerSecurityGroup"]["Properties"]
        self.assertEqual([], security_group["SecurityGroupIngress"])
        self.assertEqual({80, 443}, {
            rule["FromPort"] for rule in security_group["SecurityGroupEgress"]
        })

    def test_oidc_trust_is_exact_and_ec2_mutation_is_brokered(self):
        role = self.template["Resources"]["KvmRunnerProvisionRole"]["Properties"]
        trust = role["AssumeRolePolicyDocument"]["Statement"][0]
        condition = trust["Condition"]
        self.assertEqual(
            "sts.amazonaws.com",
            condition["StringEquals"]["token.actions.githubusercontent.com:aud"],
        )
        self.assertIn(
            "repo:${GitHubOwner}/${GitHubRepository}:environment:${GitHubEnvironment}",
            condition["StringLike"]["token.actions.githubusercontent.com:sub"],
        )
        oidc_policy = str(role["Policies"][0])
        self.assertIn("lambda:InvokeFunction", oidc_policy)
        self.assertNotIn("RunInstances", oidc_policy)
        self.assertNotIn("TerminateInstances", oidc_policy)
        broker = self.template["Resources"]["KvmRunnerBrokerRole"]["Properties"]
        statements = broker["Policies"][0]["PolicyDocument"]["Statement"]
        launch = [statement for statement in statements if statement["Action"] == "ec2:RunInstances"]
        self.assertEqual(5, len(launch))
        self.assertTrue(all(statement["Resource"] != "*" for statement in launch))
        function = self.template["Resources"]["KvmRunnerBrokerFunction"]["Properties"]
        self.assertEqual(1, function["ReservedConcurrentExecutions"])
        self.assertIn("workflow run is not current protected main", self.template_text)
        self.assertNotIn("iam:PassRole", self.template_text)
        self.assertIn("ec2:MetadataHttpPutResponseHopLimit: 1", self.template_text)

    def test_ami_storage_and_cleanup_roles_are_fail_closed(self):
        resources = self.template["Resources"]
        self.assertIn("KvmRunnerCleanupRole", resources)
        cleanup_policy = resources["KvmRunnerCleanupRole"]["Properties"]["Policies"][0]
        cleanup_text = str(cleanup_policy)
        self.assertNotIn("RunInstances", cleanup_text)
        self.assertNotIn("TerminateInstances", cleanup_text)
        self.assertIn("lambda:InvokeFunction", cleanup_text)
        cleanup_broker = str(
            resources["KvmRunnerCleanupBrokerRole"]["Properties"]["Policies"][0]
        )
        self.assertNotIn("RunInstances", cleanup_broker)
        self.assertIn("TerminateInstances", cleanup_broker)
        self.assertIn("ec2:Owner", self.template_text)
        self.assertIn("ec2:Encrypted", self.template_text)
        self.assertIn("ec2:VolumeSize", self.template_text)
        self.assertIn("ec2:VolumeType", self.template_text)
        self.assertIn("ubuntu-noble-24.04-arm64-server-", self.template_text)

    def test_cleanup_requires_exact_ownership_before_termination(self):
        cleanup_broker = self.template["Resources"]["KvmRunnerCleanupFunction"][
            "Properties"
        ]["Code"]["ZipFile"]
        for marker in (
            'tags.get("Project") != "ecosystem-dashboard-kvm"',
            'tags.get("ManagedBy") != "github-actions"',
            'tags.get("GitHubRepository") != repository',
            'tags.get("GitHubRunId") != run_id',
            'tags.get("GitHubRunAttempt") != attempt',
            're.fullmatch(r"[0-9a-f]{32}", nonce)',
            "identity_mismatch",
        ):
            self.assertIn(marker, cleanup_broker)
        self.assertIn("aws lambda invoke", self.cleanup_text)
        self.assertIn("instance-terminated", self.cleanup_text)
        self.assertIn("describe-volumes", self.cleanup_text)
        self.assertIn("describe-network-interfaces", self.cleanup_text)

    def test_partial_provisioning_removes_instance_and_registration(self):
        failure_handler = self.provision_text.split("cleanup_on_failure()", 1)[1].split(
            "trap cleanup_on_failure EXIT", 1
        )[0]
        self.assertIn("remove_runner_registration", failure_handler)
        self.assertIn("invoke_broker_cleanup", failure_handler)
        self.assertIn("page=$page", self.provision_text)
        self.assertIn("page=$page", self.cleanup_text)
        self.assertIn("run_attempt: $attempt", self.cleanup_text)
        self.assertIn(
            "ecosystem-kvm-${SOURCE_RUN_ID}-${SOURCE_RUN_ATTEMPT}",
            self.cleanup_text,
        )

    def test_inline_broker_functions_compile(self):
        resources = self.template["Resources"]
        for logical_name in (
            "KvmRunnerBrokerFunction",
            "KvmRunnerCleanupFunction",
            "KvmRunnerExpiryFunction",
        ):
            source = resources[logical_name]["Properties"]["Code"]["ZipFile"]
            compile(source, f"{logical_name}.py", "exec")

    def test_jit_runner_is_ephemeral_pinned_and_locally_capable(self):
        self.assertIn('file_map[".runner"]', self.provision_text)
        self.assertIn('settings.get("DisableUpdate") is not True', self.provision_text)
        self.assertIn('settings.get("Ephemeral") is not True', self.provision_text)
        self.assertIn("actions-runner ALL=(ALL) NOPASSWD: ALL", self.provision_text)
        self.assertIn("ACTIONS_RUNNER_INPUT_JITCONFIG", self.provision_text)

    def test_conformance_artifact_contains_no_raw_runner_diagnostics(self):
        self.assertNotIn("/opt/actions-runner/_diag", self.workflow_text)
        self.assertNotIn("include-hidden-files", self.workflow_text)
        self.assertIn("kvm-conformance-evidence.json", self.workflow_text)
        self.assertIn('"credential_absence_check": "passed"', self.workflow_text)

    def test_cloudformation_schema_lint_is_checksum_locked_in_ci(self):
        requirements = CFN_REQUIREMENTS.read_text()
        self.assertIn("cfn-lint==1.60.0 --hash=sha256:", requirements)
        self.assertIn("--require-hashes", self.foundation_workflow_text)
        self.assertIn(
            "cfn-lint-venv/bin/cfn-lint", self.foundation_workflow_text
        )
        self.assertIn(".commit.verification.verified", self.foundation_workflow_text)

    def test_kvm_foundation_remains_supplemental_only(self):
        forbidden = (
            "provision-ephemeral-kvm-runner",
            "cleanup-ephemeral-kvm-runner",
            "ecosystem-kvm-validation",
        )
        for path in (ROOT / ".github/workflows").glob("test-*.yml"):
            text = path.read_text()
            for marker in forbidden:
                self.assertNotIn(marker, text, path)

    def test_cleanup_phases_run_independently_and_reconcile_outcomes(self):
        cleanup_steps = self.cleanup["runs"]["steps"]
        by_id = {step.get("id"): step for step in cleanup_steps if step.get("id")}
        self.assertTrue(by_id["ec2-cleanup"]["continue-on-error"])
        self.assertTrue(by_id["runner-app-token"]["continue-on-error"])
        self.assertTrue(by_id["registration-cleanup"]["continue-on-error"])
        self.assertIn("always()", by_id["registration-cleanup"]["if"])
        self.assertIn("Require both cleanup phases to succeed", self.cleanup_text)

    def test_workflow_is_manual_main_only_and_targets_group_plus_random_label(self):
        self.assertIn("workflow_dispatch:", self.workflow_text)
        self.assertNotIn("pull_request_target", self.workflow_text)
        self.assertNotIn("schedule:", self.workflow_text)
        self.assertIn('test "$GITHUB_REF" = "refs/heads/main"', self.workflow_text)
        self.assertIn("group: ${{ vars.ECOSYSTEM_KVM_RUNNER_GROUP_NAME }}", self.workflow_text)
        self.assertIn("labels: ${{ needs.provision.outputs.runner-label }}", self.workflow_text)
        self.assertIn("environment: kvm-runner-provision", self.workflow_text)
        self.assertIn("environment: kvm-runner-cleanup", self.workflow_text)

    def test_untrusted_target_receives_no_privileged_token_or_environment_secret(self):
        probe = self.workflow["jobs"]["probe"]
        self.assertEqual({}, probe["permissions"])
        self.assertNotIn("environment", probe)
        serialized = yaml.safe_dump(probe)
        self.assertNotIn("secrets.", serialized)
        self.assertNotIn("actions/checkout", serialized)
        self.assertIn("ACTIONS_ID_TOKEN_REQUEST_TOKEN", self.workflow_text)
        self.assertIn("ECOSYSTEM_KVM_RUNNER_APP_PRIVATE_KEY", self.workflow_text)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", self.workflow_text)

    def test_cleanup_is_unconditional_after_provision_attempt(self):
        cleanup = self.workflow["jobs"]["cleanup"]
        self.assertIn("always()", cleanup["if"])
        self.assertIn("probe", cleanup["needs"])
        self.assertIn("provision", cleanup["needs"])


if __name__ == "__main__":
    unittest.main()
