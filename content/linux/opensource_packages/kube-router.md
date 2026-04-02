---
name: Kube-Router
category: Networking
description: Kube-router is a lightweight networking solution for Kubernetes that replaces kube-proxy and kube-dns by handling routing, network policies, and service proxying using standard Linux networking tools.
download_url: https://github.com/cloudnativelabs/kube-router/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.1.0
    release_date: 2018/03/19


optional_info:
    homepage_url: https://www.kube-router.io/
    support_caveats: Official prebuilt linux-arm64 binaries were introduced in version 1.0.0-rc4, improving accessibility and eliminating the need for manual builds on Arm systems.
    alternative_options:
    getting_started_resources:
        official_docs: https://www.kube-router.io/docs/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/cloudnativelabs/kube-router/releases/tag/v0.1.0
    release_notes__recommended_minimum:
    other_info: Version 0.1.0 adds cross-compile support for Arm. However, the native build support for Arm is added in version [0.2.0-beta.8](https://github.com/cloudnativelabs/kube-router/releases/tag/v0.2.0-beta.8), and the official linux-arm64 kube-router binary is available from version [1.0.0-rc4](https://github.com/cloudnativelabs/kube-router/releases/tag/v1.0.0-rc4) on the GitHub releases.

---

