---
name: Minikube
category: Containers and Orchestration
description: Minikube is a lightweight tool that enables you to run a single-node Kubernetes cluster locally on your machine. It's primarily used for development and testing purposes, allowing developers to experiment with Kubernetes without needing a full-fledged cloud environment.
download_url: https://github.com/kubernetes/minikube/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.10.0
    release_date: 2020/05/12


optional_info:
    homepage_url: https://minikube.sigs.k8s.io/docs/
    support_caveats: Starting with K3s v1.24.14+k3s1, support for ARM64 systems with 64KB page sizes was introduced. Earlier versions required a 4KB page size. For compatibility with 64KB page size systems, use v1.24.14+k3s1 or newer.
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/learning-paths/embedded-and-microcontrollers/cloud-native-deployment-on-hybrid-edge-systems/k3s/
        partner_content: 
        official_docs: https://minikube.sigs.k8s.io/docs/start/
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content: 
        rationale:

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/kubernetes/minikube/releases/tag/v1.10.0
    release_notes__recommended_minimum:
    other_info: Version 1.10.0 released minikube-linux-arm64 official binary on GitHub releases.

---
