---
name: Linkerd
category: Service Mesh
description: Linkerd is an ultralight, security-first service mesh for Kubernetes. It adds security, observability, and reliability to Kubernetes, without the complexity.
download_url: https://github.com/linkerd/linkerd2/releases
works_on_arm: true
supported_minimum_version:
  version_number: edge-20.8.1
  release_date: 2020/08/12
optional_info:
  homepage_url: https://linkerd.io/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/service-mesh-with-linkerd-and-arm-based-k8s
    partner_content:
      - display_name: Amazon AWS
        url: https://awsgravitonweekly.com/posts/aws-graviton-weekly-33
    official_docs: https://linkerd.io/docs/
  arm_recommended_minimum_version:
    version_number: stable-2.11.2
    release_date: 2022/04/21
    reference_content: https://github.com/linkerd/linkerd2/releases/tag/stable-2.11.2
    rationale: This version upgraded jaeger to v1.31 and opentelemetry-collector to v0.43 to support ARM architecture. Additionally, it fixed a configuration issue that prevented multicluster gateways from running on ARM nodes.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/linkerd/linkerd2/releases/tag/edge-20.8.1
  release_notes__recommended_minimum: null
  other_info: Linkerd is developed in the [Linkerd GitHub repository](https://github.com/linkerd/linkerd2). Releases and packages of Linkerd are available in several different forms. Kindly consider [this](https://linkerd.io/releases/).
---
