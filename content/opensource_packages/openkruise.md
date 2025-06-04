---
name: OpenKruise
category: DevOps
description: OpenKruise is an extended component suite for Kubernetes, which mainly focuses on application automations, such as deployment, upgrade, ops and availability protection.
download_url: https://github.com/openkruise/kruise/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.10.0
    release_date: 2021/12/14


optional_info:
    homepage_url: https://openkruise.io/en-us/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content: https://www.alibabacloud.com/blog/597549
        official_docs: https://openkruise.io/docs/installation/
    arm_recommended_minimum_version:
        version_number: 1.7.0
        release_date: 2024/08/28
        reference_content: https://github.com/openkruise/kruise/releases/tag/v1.7.0
        rationale: This release changes e2e centos image from 6.7 to 7, so that e2e can work on arm node. This release also introduces major enhancements across CloneSet, SidecarSet, StatefulSet, and ImagePullJob. CloneSet now always recreates pods when volumeClaimTemplates change. Kubernetes dependency is bumped to 1.28, with compatibility retained down to 1.18. SidecarSet adds native support for K8s 1.28 Sidecar Containers with improved lifecycle handling. ImagePullJob supports credential provider plugins like AWS. Advanced StatefulSet gains start ordinal support and pod index labels. Additional features include webhook CA injection via cert-manager, cri-docker.sock support in kruise-daemon, and structured logging. Performance is boosted via SidecarSet controller optimizations and reduced Pod update conflicts.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes or binaries released for ARM64. To install minimum version, OpenKruise requires Kubernetes 1.18+ version.

---

