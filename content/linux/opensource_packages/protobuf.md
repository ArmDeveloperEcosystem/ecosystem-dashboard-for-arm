---
name: Protobuf
category: Data-format
description: Protocol Buffers (protobuf) is Google's language-neutral, platform-neutral, extensible mechanism for serializing structured data. 
download_url: https://github.com/protocolbuffers/protobuf/releases
works_on_arm: true
supported_minimum_version:
    version_number: v3.5.0
    release_date: 2017/11/16
 
 
optional_info:
    homepage_url: https://github.com/protocolbuffers/protobuf
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/protocolbuffers/protobuf/blob/main/src/README.md
        arm_content: https://developer.arm.com/documentation/ka002171/latest/
        partner_content:
    arm_recommended_minimum_version:
        version_number: 4.21.0
        release_date: 2022/05/06
        reference_content: https://protobuf.dev/news/2022-05-06/
        rationale: Version 4.21.0 introduced significant performance improvements by adopting the upb library, resulting in notably better parsing performance, especially for large payloads. While these enhancements are general, they benefit Arm-based systems by improving overall efficiency.
 
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/protocolbuffers/protobuf/releases/tag/v3.5.0
    release_notes__recommended_minimum: 
    other_info: There are no release notes for the minimum version for ARM64, but binary for aarch64 Linux are published with each release starting from v3.5.0.
 
---

