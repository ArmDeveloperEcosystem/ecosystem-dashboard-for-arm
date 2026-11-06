# Ephemeral Arm64 KVM runner

This foundation provides supplemental real Arm64 virtualization validation
without placing a persistent self-hosted runner in the public dashboard
repository. Every target
is a new `c7g.metal` instance, accepts one GitHub Actions job through a JIT
configuration, and is terminated after that job.

It is intentionally inactive until every activation prerequisite below is
complete and the manual conformance workflow is green on protected `main`.

## Trust boundaries

1. A GitHub-hosted `ubuntu-24.04-arm` coordinator runs only the reviewed
   workflow from protected `main`.
2. GitHub OIDC grants that coordinator a short AWS session which can invoke a
   fixed launch broker and read instance state. The OIDC role cannot call
   `RunInstances` or `TerminateInstances`. The broker revalidates the live
   GitHub run, protected `main` SHA, workflow path, original actor, and rerun
   actor before serially launching one reviewed Ubuntu Arm64 `c7g.metal`
   target in the isolated VPC.
3. A GitHub App installed only on this repository creates a one-job JIT runner
   configuration in a dedicated organization runner group. The registration
   carries only a random per-run label. Its private key remains in protected
   coordinator environments.
4. The target receives only the one-time JIT configuration. It receives no App
   key, AWS identity, environment secret, privileged repository permission,
   token environment injection, or OIDC permission.
5. Normal cleanup invokes a separate cleanup-only broker which verifies the
   exact repository, run, attempt, instance, type, and random ownership tag
   before termination. The unreviewed cleanup environment cannot invoke the
   launch broker. EC2 shutdown behavior, a host-local timer, and a five-minute
   AWS expiry janitor provide independent cleanup paths.

## Activation prerequisites

### Dedicated runner group

An `ArmDeveloperEcosystem` owner must create an organization runner group named
`ecosystem-kvm-validation` with all of these settings:

- repository access: only `ecosystem-dashboard-for-arm`;
- workflow access: only the reviewed KVM foundation and KVM package workflows
  on the default branch;
- no public-repository fork workflow access;
- no runner registrations outside this automation.

The default runner group is forbidden. Record the numeric group ID and name as
repository variables:

- `ECOSYSTEM_KVM_RUNNER_GROUP_ID`
- `ECOSYSTEM_KVM_RUNNER_GROUP_NAME`
- `ECOSYSTEM_KVM_ALLOWED_ACTORS_JSON`, for example
  `["ranimandepudi","pareenaverma"]`

Every target job must select both this group and the random label emitted by
the provision action. The registration must not include static labels such as
`self-hosted`, `Linux`, `ARM64`, or `ecosystem-kvm`; a job selecting a broad
static label is non-compliant. Both the original dispatcher and any actor who
reruns the workflow must appear in the allowed-actors variable.

### Repository-scoped GitHub App

Create the organization-owned App `Arm Ecosystem KVM Runner` and install it
only on `ArmDeveloperEcosystem/ecosystem-dashboard-for-arm`.

Required repository permission:

- Administration: read and write, solely for JIT runner registration.

Do not grant organization permissions, webhooks, Contents, Actions, Pull
requests, Issues, Secrets, Environments, or Workflows permissions. Store:

- App ID as repository variable `ECOSYSTEM_KVM_RUNNER_APP_ID`;
- private key as environment secret
  `ECOSYSTEM_KVM_RUNNER_APP_PRIVATE_KEY`.

The App token is minted immediately before registration and GitHub's token
action revokes it in post-job cleanup.

### Protected environments

Create `kvm-runner-provision` in the dashboard repository. Restrict deployment
branches to `main` only, do not allow tag deployments, and require an
independent infrastructure reviewer. Create a second environment,
`kvm-runner-cleanup`, restricted to `main` with no reviewer wait so termination
cannot be blocked. Store the App private key in both environments. The
provisioning role trusts only the first environment and the cleanup-only role
trusts only the second. The workflow also rejects any repository or ref other
than canonical `main`, rejects unauthorized original or rerun actors, and
compares its commit with the current `main` head before any App or AWS token is
minted.

### AWS stack

Deploy `.github/infrastructure/ecosystem-kvm-runner.yaml` in the approved AWS
account. It creates a small isolated VPC with no peering, transit gateway, VPN,
or route to corporate networks; an outbound-only security group; exact GitHub
OIDC roles; serialized launch and cleanup brokers; and an expiry Lambda.

Use the current Canonical Ubuntu 24.04 Arm64 server AMI owned by account
`099720109477` and an availability zone with `c7g.metal` capacity. The region
must have room for the dedicated VPC and internet gateway before deployment;
do not reuse or delete an existing workload VPC to make room without its
owner's approval. The launch broker has reserved concurrency one, rejects a
launch while any managed target is active, fixes the AMI, instance type,
network, storage, metadata, shutdown behavior, and tags, and independently
queries GitHub before every launch. Regional EC2 quota is not treated as a
security control. Copy these stack outputs to repository variables:

- `ECOSYSTEM_KVM_AWS_ROLE_ARN`
- `ECOSYSTEM_KVM_AWS_CLEANUP_ROLE_ARN`
- `ECOSYSTEM_KVM_BROKER_FUNCTION_NAME`
- `ECOSYSTEM_KVM_CLEANUP_FUNCTION_NAME`
- `ECOSYSTEM_KVM_REGION`

The target has a public address only for outbound GitHub and package downloads.
It has no inbound security-group rule, key pair, instance profile, or metadata
endpoint. HTTP is permitted only because Ubuntu mirrors may redirect to HTTPS;
all other outbound TCP ports are denied. IAM additionally requires the exact
Canonical publisher, Arm64 HVM image properties, encrypted 40-GiB `gp3`
storage, reviewed subnet and security group, and lifecycle tags. Neither GitHub
OIDC role can mutate EC2 directly.

The one-job `actions-runner` account has passwordless local `sudo` so isolated
supplemental KVM probes can install dependencies and configure guests. This is
root-equivalent only inside the disposable target: the job has no App key, AWS
identity, OIDC permission, repository write token, inbound path, or metadata
service, and external cleanup does not trust the guest operating system.

## Conformance run

After the stack, group, App, variables, and secret exist:

1. Open **Actions > Validate ephemeral Arm64 KVM runner** on `main`.
2. Run it with confirmation `PROVISION-KVM`.
3. Require all four jobs to finish successfully.
4. Confirm the probe proves native AArch64, KVM API version 12, VM creation,
   absent cloud/App/OIDC credentials, and an unreachable metadata endpoint.
5. Download and retain the 14-day sanitized conformance artifact. Raw runner
   and worker diagnostic logs are deliberately not uploaded.
6. Confirm cleanup reports no tagged volume, network interface, runner
   registration, or active instance.
7. Confirm the expiry Lambda has no overdue instance to terminate and both
   CloudWatch alarms are healthy.

Do not add a supplemental package KVM lane until this run is green. Under the
current dashboard publication contract, registered `test-*.yml` workflows must
remain a single job on GitHub-hosted `ubuntu-24.04-arm`; self-hosted evidence is
not accepted as authoritative package-result evidence. Firecracker,
Microsandbox, and libkrun therefore keep their strict hosted six-test workflow,
while a separately named supplemental workflow uses these shared provision and
cleanup actions for real guest execution. Making KVM evidence authoritative
would require a separately reviewed, versioned migration of aggregation,
attestation, batch, runner-label, and publication policy. A missing KVM target
in the supplemental lane remains a failure, never a skip-to-pass.

## Incident and cost controls

- Disable the GitHub App installation to stop new JIT registrations.
- Disable the `kvm-runner-provision` environment to stop AWS role assumption.
- Disable the provisioning OIDC role or launch broker to stop all new
  instances. Keep the cleanup broker and expiry janitor enabled until all
  tagged targets are confirmed terminated.
- Instances carry `Project`, repository, run, attempt, random ownership, and
  expiry tags. Never terminate an unverified instance from workflow code.
- The maximum target lifetime is 60 minutes, and normal runs request 45
  minutes. The AWS janitor checks every five minutes independently of GitHub,
  caps lifetime at 60 minutes from EC2 launch even if an expiry tag is changed,
  terminates duplicate runners, and publishes active-runner metrics.
- Cleanup discovers resources by exact run and attempt tags even when the
  coordinator dies before publishing outputs. Registration cleanup derives the
  deterministic JIT runner name from the same run identity.
- Treat the multiplicity or janitor-error CloudWatch alarm as an incident and
  disable the provisioning role until the account is reconciled.
- Review App installation changes, OIDC role usage, Lambda expiry events, and
  EC2 cost after each initial package validation before enabling a schedule.

