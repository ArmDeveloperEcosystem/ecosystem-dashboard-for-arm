---
name: Kubectl
category: Containers and Orchestration
description: Kubectl is a command-line tool for interacting with Kubernetes, enabling users to manage and operate cluster resources.
download_url: https://kubernetes.io/releases/download/
works_on_arm: true
supported_minimum_version:
    version_number: 1.3.0
    release_date: 2016/07/02
 
 
optional_info:
    homepage_url: https://kubernetes.io/docs/reference/kubectl/introduction/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://kubernetes.io/docs/reference/kubectl/quick-reference/
        arm_content: https://learn.arm.com/install-guides/kubectl/
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Kubectl is a part of Kubernetes, and there is no specific release that mentions the initial Linux/Arm64 support for Kubectl. However, 64-bit ARM support is introduced in kubernetes from version 1.3.0 onwards, and kubectl can be installed on Linux/Arm64 platforms using "wget https://dl.k8s.io/release/v1.3.0/bin/linux/arm64/kubectl". Kindly refer [this](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.3.md). 
 
---
