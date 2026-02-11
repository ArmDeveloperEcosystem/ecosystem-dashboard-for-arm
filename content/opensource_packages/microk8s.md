---
name: MicroK8s
category: Containers and Orchestration
description: MicroK8s, developed and maintained by Canonical, is a lightweight, secure, and production-grade Kubernetes distribution that provides a simple, single-package install for developers and enterprises. It offers seamless compatibility with major managed K8s services, includes batteries-included features like service mesh, serverless, monitoring, and GPU support, while closely tracking upstream Kubernetes releases.
download_url: https://github.com/canonical/microk8s/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.13
    release_date: 2019/02/14
 
 
optional_info:
    homepage_url: https://microk8s.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://microk8s.io/#install-microk8s
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.28.0
        release_date: 2023/08/06
        reference_content: https://github.com/canonical/microk8s/releases/tag/v1.28
        rationale: In this release, ArgoCD was upgraded to v2.7.2 and goppadle to v4.2.9, with both components now providing official Arm64 support, enhancing overall efficiency and compatibility for MicroK8s Arm64 clusters.
 
optional_hidden_info:
    release_notes__supported_minimum: https://microk8s.io/docs/release-notes#p-19989-microk8s-113-14-february-2019
    release_notes__recommended_minimum:
    other_info:
 
---
