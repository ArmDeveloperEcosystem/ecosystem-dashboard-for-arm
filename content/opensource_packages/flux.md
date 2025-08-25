---
name: Flux
category: DevOps
description: Flux is an open and extensible continuous delivery solution for Kubernetes.
download_url: https://github.com/fluxcd/flux2/releases
works_on_arm: true
supported_minimum_version:
  version_number: 0.0.21
  release_date: 2020/09/04
optional_info:
  homepage_url: https://fluxcd.io/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Microsoft Azure
        url: https://learn.microsoft.com/en-us/azure/azure-arc/kubernetes/tutorial-use-gitops-flux2?tabs=azure-cli
    official_docs: https://fluxcd.io/flux/
  arm_recommended_minimum_version:
    version_number: 2.4.0
    release_date: 2024/09/30
    reference_content: https://github.com/fluxcd/flux2/releases/tag/v2.4.0
    rationale: This release supports running ARM64 e2e tests on GitHub runners, that establishes a concrete support for the architecture. It marks a feature-rich GA release, introducing Bucket v1 API with support for mTLS, proxy, and custom STS configs for AWS S3 and MinIO. GitRepository v1 adds support for OIDC authentication, enabling seamless Azure DevOps integration via AKS Workload Identity. OCIRepository v1beta2 now supports proxy authentication for container registries. HelmRelease v2 gains options to disable JSON schema validation during install and upgrade, and to adopt existing Kubernetes resources. Controllers are updated to Go 1.23, Kubernetes 1.31, Helm 3.16, SOPS 3.9, Cosign 2.4, and Notation 1.2. Compatible with Kubernetes v1.29+, Flux also supports deployment on OpenShift via OperatorHub with full multi-tenancy and scaling features.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/fluxcd/flux2/releases/tag/v0.0.21
  release_notes__recommended_minimum: null
  other_info: null
---
