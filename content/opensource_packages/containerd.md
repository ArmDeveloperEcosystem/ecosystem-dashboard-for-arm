---
name: Containerd
category: Runtimes
description: Containerd is an industry-standard container runtime with an emphasis on simplicity, robustness, and portability.
download_url: https://containerd.io/downloads/
works_on_arm: true
supported_minimum_version:
    version_number: 1.6.0
    release_date: 2022/02/16


optional_info:
    homepage_url: https://containerd.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/container-runtimes-wasmedge-arm
        partner_content: https://aws.amazon.com/blogs/containers/all-you-need-to-know-about-moving-to-containerd-on-amazon-eks/
        official_docs: https://containerd.io/docs/getting-started/
    arm_recommended_minimum_version:
        version_number: 2.0.0
        release_date: 2024/11/06
        reference_content: https://github.com/containerd/containerd/releases/tag/v2.0.0
        rationale: This release focuses on the continued stability of containerd's core feature set with an easy upgrade from containerd 1.x. This release includes the stabilization of new features added in the last 1.x release as well as the removal of features which were deprecated in 1.x.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/containerd/containerd/releases/tag/v1.6.0
    release_notes__recommended_minimum:
    other_info: No ARM64 specific realease notes available but the first binary for ARM64 was released from v1.6.0.

---
