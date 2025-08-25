---
name: Keda
category: Miscellaneous
description: KEDA is a Kubernetes-based Event Driven Autoscaling component. It provides event driven scale for any container running in Kubernetes.
download_url: https://github.com/kedacore/keda/pkgs/container/keda
works_on_arm: true
supported_minimum_version:
  version_number: 2.7.0
  release_date: 2022/05/05
optional_info:
  homepage_url: https://keda.sh/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/compute/mixing-aws-graviton-with-x86-cpus-to-optimize-cost-and-resilience-using-amazon-eks/
    official_docs: https://keda.sh/docs/2.13/deploy/
  arm_recommended_minimum_version:
    version_number: 2.8.0
    release_date: 2022/08/10
    reference_content: https://github.com/kedacore/keda/releases/tag/v2.8.0
    rationale: This version introduced over 50 built-in scalers, including new AWS DynamoDB Streams and NATS JetStream scalers. It added support for Azure AD Workload Identity, minReplicaCount for ScaledJobs, and HPA name customization. Improvements include better logging, reduced connection overhead, and leader election settings. The release also patched CVE-2022-27191 and fixed ARM64 devcontainer issues. Deprecated rolloutStrategy in favor of rollout.strategy.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/kedacore/keda/blob/main/CHANGELOG.md#v270
  release_notes__recommended_minimum: null
  other_info: Binaries are not available for both AMD64 and ARM64 platforms. Releasing Docker image for both ARM64 and AMD64 from version [2.7.0](https://github.com/kedacore/keda/pkgs/container/keda/21356119?tag=2.7.0)
---
