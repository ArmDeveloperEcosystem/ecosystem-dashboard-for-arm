---
name: DynamoRio
category: Runtimes
description: DynamoRIO is a dynamic binary instrumentation tool that provides a runtime code manipulation system.
download_url: https://github.com/DynamoRIO/dynamorio/releases
works_on_arm: true
supported_minimum_version:
    version_number: 7.0.0-RC1
    release_date: 2017/02/04


optional_info:
    homepage_url: https://dynamorio.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/high-performance-computing-blog/posts/emulating-sve-on-armv8-using-dynamorio-and-armie
        partner_content:
        official_docs: https://dynamorio.org/page_user_docs.html
    arm_recommended_minimum_version:
        version_number: 9.0.1
        release_date: 2022/02/15
        reference_content: https://github.com/DynamoRIO/dynamorio/releases/tag/release_9.0.1
        rationale: DynamoRIO 9.0.1 introduces key enhancements and broader platform compatibility. A major addition is the experimental -attach option in drrun for attaching to running processes (currently x86-only). The release significantly improves AArch64 (ARM64) support and adds a new library for Linux-based application callstack walking. Support was also added for running mixed-bitwidth child processes (e.g., 32-bit under 64-bit) and preliminary execution under QEMU. These features extend DynamoRIO’s dynamic instrumentation capabilities across more environments and use cases.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/DynamoRIO/dynamorio/releases/tag/release_7_0_0_rc1
    release_notes__recommended_minimum:
    other_info:

---
