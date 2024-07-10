---
name: GVisor
category: Containers and Orchestration
description: GVisor is an open-source Linux-compatible sandbox that runs anywhere existing container tooling does. It enables cloud-native container security and portability.
download_url: https://github.com/google/gvisor/tags
works_on_arm: true
supported_minimum_version:
    version_number: release-20210121.1
    release_date: 2021/01/28


optional_info:
    homepage_url: https://gvisor.dev/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/serverless-on-arm64
        partner_content: https://static.linaro.org/connect/lvc21f/presentations/LVC21F-204.pdf
        official_docs: https://gvisor.dev/docs/user_guide/compatibility/linux/arm64/
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: No specific release notes are available for Linux/ARM64. However, gVisor can be installed for aarch64 from version 20210121.1 onwards using the download URL <https://storage.googleapis.com/gvisor/releases/release/${yyyymmdd}.${rc}/${ARCH}> and [this](https://gvisor.dev/docs/user_guide/install/) install guide.

---
