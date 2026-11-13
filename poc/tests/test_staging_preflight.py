"""Exercise staging discovery without credentials, network calls or cloud writes."""

import json
import subprocess

import pytest

from poc.deploy import preflight


ACCOUNT = "123456789012"
INSTANCE = "i-0123456789abcdef0"
CANARY = "PRIVATE_RESPONSE_MUST_NOT_APPEAR"
READ_ONLY = {
    ("sts", "get-caller-identity"),
    ("cloudfront", "get-distribution-config"),
    ("s3api", "get-bucket-location"),
    ("cloudformation", "describe-stack-resources"),
    ("autoscaling", "describe-auto-scaling-groups"),
    ("ec2", "describe-instances"),
    ("ssm", "describe-instance-information"),
}


@pytest.fixture
def cloud(monkeypatch):
    responses = {
        "sts": {"Account": ACCOUNT, "Arn": CANARY},
        "cloudfront": {"DistributionConfig": {
            "DefaultCacheBehavior": {"TargetOriginId": "static"},
            "Origins": {"Items": [{"Id": "static", "OriginPath": "",
                                    "DomainName": "armsoftwaredev.tk.s3.amazonaws.com"}]},
            "CacheBehaviors": {"Items": []},
            "CallerReference": CANARY,
        }},
        "s3api": {"LocationConstraint": None},
        "cloudformation": {"StackResources": [{
            "ResourceType": "AWS::AutoScaling::AutoScalingGroup",
            "PhysicalResourceId": "fixture-group",
        }]},
        "autoscaling": {"AutoScalingGroups": [{
            "AutoScalingGroupName": "fixture-group",
            "Instances": [{"InstanceId": INSTANCE}],
        }]},
        "ec2": {"Reservations": [{"Instances": [{
            "InstanceId": INSTANCE, "State": {"Name": "running"},
            "PrivateDnsName": CANARY,
        }]}]},
        "ssm": {"InstanceInformationList": [{
            "InstanceId": INSTANCE, "PingStatus": "Online",
            "PlatformName": "Ubuntu", "ComputerName": CANARY,
        }]},
    }
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert command[0] == "aws"
        assert tuple(command[1:3]) in READ_ONLY
        return subprocess.CompletedProcess(command, 0, json.dumps(responses[command[1]]), CANARY)

    monkeypatch.setattr(preflight.subprocess, "run", run)
    return responses, calls


def test_verified_metadata_uses_only_reads_and_never_claims_deployment_ready(cloud):
    _, calls = cloud
    report = preflight.run_preflight(ACCOUNT, "us-west-2", "FixtureStack")
    assert report["passed"] and report["ready_for_host_review"]
    assert report["deployment_ready"] is False
    assert {tuple(command[1:3]) for command, _ in calls} == READ_ONLY
    serialized = json.dumps(report)
    for private_value in (ACCOUNT, INSTANCE, CANARY, "fixture-group", "FixtureStack"):
        assert private_value not in serialized


def test_account_mismatch_prevents_all_backend_reads(cloud):
    _, calls = cloud
    report = preflight.run_preflight("999999999999", "us-west-2", "FixtureStack")
    assert not report["passed"] and not report["ready_for_host_review"]
    assert {command[1] for command, _ in calls} == {"sts", "cloudfront", "s3api"}


def test_static_only_discovery_does_not_choose_a_backend(cloud):
    _, calls = cloud
    report = preflight.run_preflight(ACCOUNT)
    assert report["backend"]["status"] == "not_requested"
    assert not report["ready_for_host_review"] and not report["deployment_ready"]
    assert {command[1] for command, _ in calls} == {"sts", "cloudfront", "s3api"}


@pytest.mark.parametrize("account,region,stack", [
    ("", "", ""), ("123", "", ""), ("12345678901\n", "", ""),
    (ACCOUNT, "us-west-2", ""), (ACCOUNT, "", "FixtureStack"),
    (ACCOUNT, "us-west-2 --debug", "FixtureStack"),
    (ACCOUNT, "us-west-2", "--all"), (ACCOUNT, "us-west-2", "stack; id"),
])
def test_malformed_configuration_fails_before_any_aws_call(cloud, account, region, stack):
    _, calls = cloud
    report = preflight.run_preflight(account, region, stack)
    assert report["status"] == "invalid_configuration"
    assert not report["passed"] and not calls


@pytest.mark.parametrize("condition", [
    "no_asg", "multiple_asgs", "no_instances", "too_many_instances",
    "stopped", "unrelated_instance", "unmanaged", "offline", "wrong_os",
])
def test_unverified_host_metadata_never_becomes_ready(cloud, condition):
    responses, _ = cloud
    if condition == "no_asg":
        responses["cloudformation"]["StackResources"] = []
    elif condition == "multiple_asgs":
        responses["cloudformation"]["StackResources"] *= 2
    elif condition in ("no_instances", "too_many_instances"):
        responses["autoscaling"]["AutoScalingGroups"][0]["Instances"] = (
            [] if condition == "no_instances" else
            [{"InstanceId": f"i-{index:017x}"} for index in range(21)]
        )
    elif condition == "stopped":
        responses["ec2"]["Reservations"][0]["Instances"][0]["State"]["Name"] = "stopped"
    elif condition == "unrelated_instance":
        responses["ec2"]["Reservations"][0]["Instances"][0]["InstanceId"] = "i-00000000000000000"
    elif condition == "unmanaged":
        responses["ssm"]["InstanceInformationList"] = []
    elif condition == "offline":
        responses["ssm"]["InstanceInformationList"][0]["PingStatus"] = "ConnectionLost"
    else:
        responses["ssm"]["InstanceInformationList"][0]["PlatformName"] = "Amazon Linux"
    report = preflight.run_preflight(ACCOUNT, "us-west-2", "FixtureStack")
    assert not report["passed"] and not report["ready_for_host_review"]
    assert report["deployment_ready"] is False


@pytest.mark.parametrize("failure,expected_status", [
    ("denied", "access_denied"), ("error", "unavailable"),
    ("timeout", "timed_out"), ("malformed", "invalid_response"),
    ("wrong_shape", "invalid_response"), ("missing_cli", "unavailable"),
])
def test_cli_failures_discard_raw_output(monkeypatch, capsys, failure, expected_status):
    def run(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 25, output=CANARY, stderr=CANARY)
        if failure == "missing_cli":
            raise FileNotFoundError(CANARY)
        return subprocess.CompletedProcess(
            command, 1 if failure in ("denied", "error") else 0,
            json.dumps([CANARY]) if failure == "wrong_shape" else CANARY,
            ("AccessDenied " if failure == "denied" else "") + CANARY,
        )

    monkeypatch.setattr(preflight.subprocess, "run", run)
    assert preflight.aws("sts", "get-caller-identity", "us-east-1") == (None, expected_status)
    assert capsys.readouterr() == ("", "")


def test_cli_is_bounded_and_cannot_inherit_endpoint_or_profile_overrides(monkeypatch, cloud):
    _, calls = cloud
    for name in ("AWS_ENDPOINT_URL", "AWS_PROFILE", "AWS_CONFIG_FILE",
                 "AWS_SHARED_CREDENTIALS_FILE", "AWS_WEB_IDENTITY_TOKEN_FILE"):
        monkeypatch.setenv(name, CANARY)
    preflight.aws("sts", "get-caller-identity", "us-east-1")
    command, options = calls[0]
    assert options["timeout"] <= 30
    assert options["capture_output"] and options["text"]
    assert not options.get("shell", False)
    for flag in ("--cli-connect-timeout", "--cli-read-timeout"):
        assert 0 < int(command[command.index(flag) + 1]) <= 10
    assert CANARY not in options["env"].values()
    assert options["env"]["AWS_EC2_METADATA_DISABLED"] == "true"


@pytest.mark.parametrize("service,operation", [
    ("ssm", "send-command"), ("ec2", "run-instances"),
    ("cloudformation", "deploy"), ("s3api", "put-object"),
])
def test_write_operations_are_rejected_before_cli_execution(cloud, service, operation):
    _, calls = cloud
    with pytest.raises(ValueError, match="read-only"):
        preflight.aws(service, operation, "us-west-2")
    assert not calls


def test_main_sanitizes_malformed_nested_provider_response(monkeypatch, cloud, capsys):
    responses, _ = cloud
    responses["cloudfront"]["DistributionConfig"]["Origins"]["Items"] = [CANARY]
    monkeypatch.setenv("EXPECTED_BACKEND_ACCOUNT", ACCOUNT)
    monkeypatch.setenv("BACKEND_REGION", "us-west-2")
    monkeypatch.setenv("BACKEND_STACK", "FixtureStack")
    assert preflight.main() == 1
    output = capsys.readouterr()
    assert not output.err and CANARY not in output.out
    assert json.loads(output.out)["passed"] is False
