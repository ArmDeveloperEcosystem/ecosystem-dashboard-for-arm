"""Read-only staging discovery. Print only allowlisted, nonidentifying findings."""

import json
import os
import re
import subprocess


OPERATIONS = {
    ("sts", "get-caller-identity"),
    ("cloudfront", "get-distribution-config"),
    ("s3api", "get-bucket-location"),
    ("cloudformation", "describe-stack-resources"),
    ("autoscaling", "describe-auto-scaling-groups"),
    ("ec2", "describe-instances"),
    ("ssm", "describe-instance-information"),
}
BUCKET = "armsoftwaredev.tk"
DISTRIBUTION = "EBSHXJ6P4DYP8"


def aws(service, operation, region, *arguments):
    if (service, operation) not in OPERATIONS:
        raise ValueError("AWS operation is not in the read-only allowlist")
    # Do not inherit profiles, endpoint overrides, credential processes or IMDS.
    env = {key: os.environ[key] for key in (
        "PATH", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"
    ) if key in os.environ}
    env.update(AWS_CONFIG_FILE=os.devnull, AWS_SHARED_CREDENTIALS_FILE=os.devnull,
               AWS_EC2_METADATA_DISABLED="true", AWS_PAGER="",
               AWS_CLI_AUTO_PROMPT="off", AWS_MAX_ATTEMPTS="1")
    try:
        result = subprocess.run(
            ["aws", service, operation, "--region", region, "--output", "json",
             "--cli-connect-timeout", "5", "--cli-read-timeout", "10", *arguments],
            env=env, capture_output=True, text=True, timeout=25, check=False,
        )
        if result.returncode:
            denied = any(code in result.stderr for code in (
                "AccessDenied", "UnauthorizedOperation", "Forbidden"
            ))
            return None, "access_denied" if denied else "unavailable"
        payload = json.loads(result.stdout)
        return (payload, "available") if isinstance(payload, dict) else (None, "invalid_response")
    except subprocess.TimeoutExpired:
        return None, "timed_out"
    except OSError:
        return None, "unavailable"
    except ValueError:
        return None, "invalid_response"


def run_preflight(expected_account, backend_region="", backend_stack=""):
    report = {"passed": False, "ready_for_host_review": False, "deployment_ready": False}
    if (not re.fullmatch(r"[0-9]{12}", expected_account)
            or bool(backend_region) != bool(backend_stack)
            or (backend_region and not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[1-9][0-9]*", backend_region))
            or (backend_stack and not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,127}", backend_stack))):
        return {**report, "status": "invalid_configuration"}

    identity, status = aws("sts", "get-caller-identity", "us-east-1")
    matches = status == "available" and identity.get("Account") == expected_account
    report["identity"] = {"status": status, "backend_account_matches": matches}

    # The dashboard account is not inferred from the backend's expected account.
    distribution, status = aws("cloudfront", "get-distribution-config", "us-east-1",
                               "--id", DISTRIBUTION)
    static = report["static"] = {"cloudfront": status}
    if status == "available":
        config = distribution.get("DistributionConfig", {})
        origin_id = config.get("DefaultCacheBehavior", {}).get("TargetOriginId")
        domains = {f"{BUCKET}.s3.amazonaws.com", f"{BUCKET}.s3.us-east-1.amazonaws.com",
                   f"{BUCKET}.s3-website-us-east-1.amazonaws.com"}
        static["static_origin_matches_config"] = any(
            origin.get("Id") == origin_id and origin.get("DomainName") in domains
            and origin.get("OriginPath", "") == ""
            for origin in config.get("Origins", {}).get("Items", [])
        )
        static["api_behavior_count"] = sum(
            behavior.get("PathPattern", "").lstrip("/").startswith("api/")
            for behavior in config.get("CacheBehaviors", {}).get("Items", [])
        )
    location, status = aws("s3api", "get-bucket-location", "us-east-1", "--bucket", BUCKET)
    static["bucket"] = status
    if status == "available":
        static["bucket_region_matches_config"] = (
            "LocationConstraint" in location and location["LocationConstraint"] in (None, "us-east-1")
        )

    backend = report["backend"] = {"status": "not_requested"}
    if not matches:
        backend["status"] = "account_mismatch" if identity else "identity_unavailable"
    elif backend_stack:
        backend.update(inspect_backend(backend_region, backend_stack))
    report["ready_for_host_review"] = backend["status"] == "metadata_verified"
    report["passed"] = bool(matches and static.get("static_origin_matches_config")
                            and static.get("bucket_region_matches_config")
                            and backend["status"] in ("not_requested", "metadata_verified"))
    return report


def inspect_backend(region, stack):
    payload, status = aws("cloudformation", "describe-stack-resources", region,
                          "--stack-name", stack)
    if status != "available":
        return {"status": "stack_" + status}
    groups = [item.get("PhysicalResourceId", "") for item in payload.get("StackResources", [])
              if item.get("ResourceType") == "AWS::AutoScaling::AutoScalingGroup"]
    if len(groups) != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/+=,@-]{0,254}", groups[0]):
        return {"status": "single_asg_required"}
    payload, status = aws("autoscaling", "describe-auto-scaling-groups", region,
                          "--auto-scaling-group-names", groups[0])
    if status != "available":
        return {"status": "asg_" + status}
    groups = payload.get("AutoScalingGroups", [])
    if len(groups) != 1:
        return {"status": "single_asg_required"}
    ids = [item.get("InstanceId", "") for item in groups[0].get("Instances", [])]
    if not 1 <= len(ids) <= 20 or not all(re.fullmatch(r"i-[0-9a-f]{8,17}", value) for value in ids):
        return {"status": "bounded_instance_list_required"}
    payload, status = aws("ec2", "describe-instances", region, "--instance-ids", *ids,
                          "--filters", "Name=instance-state-name,Values=running")
    if status != "available":
        return {"status": "instances_" + status}
    running = [item.get("InstanceId") for reservation in payload.get("Reservations", [])
               for item in reservation.get("Instances", [])
               if item.get("State", {}).get("Name") == "running" and item.get("InstanceId") in ids]
    result = {"status": "single_running_instance_required", "running_count": len(running)}
    if len(running) != 1:
        return result
    payload, status = aws("ssm", "describe-instance-information", region,
                          "--filters", "Key=InstanceIds,Values=" + running[0])
    if status != "available":
        return {**result, "status": "ssm_" + status}
    managed = [item for item in payload.get("InstanceInformationList", [])
               if item.get("InstanceId") == running[0]]
    result.update(managed_count=len(managed),
                  online_count=sum(item.get("PingStatus") == "Online" for item in managed),
                  ubuntu_count=sum(item.get("PlatformName") == "Ubuntu" for item in managed))
    result["status"] = "metadata_verified" if all(result[key] == 1 for key in (
        "managed_count", "online_count", "ubuntu_count"
    )) else "host_access_or_os_unverified"
    return result


def main():
    try:
        report = run_preflight(os.getenv("EXPECTED_BACKEND_ACCOUNT", ""),
                               os.getenv("BACKEND_REGION", ""), os.getenv("BACKEND_STACK", ""))
    except (TypeError, ValueError, KeyError, AttributeError):
        # Malformed provider responses must never leak private response content.
        report = {"passed": False, "deployment_ready": False, "status": "invalid_response"}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
