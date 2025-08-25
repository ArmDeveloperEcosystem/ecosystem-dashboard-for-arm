---
name: Kubernetes
category: Containers and Orchestration
description: Kubernetes is an open-source system for automating deployment, scaling, and management of containerized applications.
download_url: https://kubernetes.io/releases/download/
works_on_arm: true
supported_minimum_version:
    version_number: 1.5.0
    release_date: 2016/12/13	

optional_info:
    homepage_url: https://kubernetes.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/install-guides/kubectl/
        partner_content:
            - display_name: Oracle OCI
              url: https://docs.oracle.com/en/learn/arm_oke_cluster_oci/index.html
        official_docs: https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/
    arm_recommended_minimum_version:
        version_number: 1.32.0
        release_date: 2024/12/11
        reference_content: https://kubernetes.io/blog/2024/12/11/kubernetes-v1-32-release/
        rationale: This version enhanced the Dynamic Resource Allocation, with performance improvements for ML/AI applications.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.5.md#downloads-for-v150
    release_notes__recommended_minimum:
    other_info: No ARM64 specific realease notes available but the first binary for ARM64 was released from v1.5.0. Releases are officially supported up to 1 year post-release.
---
