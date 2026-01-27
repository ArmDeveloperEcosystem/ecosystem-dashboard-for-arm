---
name: Istio
category: Containers and Orchestration
description: Istio is an open-source service mesh that layers transparently onto existing distributed applications.
download_url: https://github.com/istio/istio/releases
works_on_arm: true
supported_minimum_version:
  version_number: 1.6.0-alpha.1
  release_date: 2020/04/10
optional_info:
  homepage_url: https://istio.io/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://github.com/istio/istio/wiki
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/deploying-tetrate-istio-distribution-for-arm-neoverse-based-aws-graviton-processors
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/opensource/getting-started-with-istio-on-amazon-eks/
  arm_recommended_minimum_version:
    version_number: 1.15
    release_date: 2022/10/27
    reference_content: https://tetrate.io/blog/the-arm64-processor-is-now-supported-in-istio-1-15/
    rationale: Istio version 1.15 introduced official support for the Arm64 architecture across both its data plane and control plane components. Prior to this release, while the data plane (Envoy) had Arm64 support, the control plane did not. This version ensures comprehensive functionality on Arm-based servers without the need for manual image builds.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/istio/istio/releases/tag/1.6.0-alpha.1
  release_notes__recommended_minimum: null
  other_info: null
---
