---
name:  LLVM Toolchain
category: Compilers/Tools
description: LLVM is a set of compiler and toolchain technologies. It is broadly capable as a frontend for any programming language and a backend for any ISA.
download_url: https://github.com/llvm/llvm-project/releases/
works_on_arm: true
supported_minimum_version:
    version_number: 7.1.0
    release_date: 2019/05/11


optional_info:
    homepage_url: https://www.linaro.org/downloads/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://llvm.org/docs/GettingStarted.html
        arm_content: https://developer.arm.com/Tools%20and%20Software/LLVM%20Toolchain#Technical-Specifications
        partner_content:
    arm_recommended_minimum_version:
        version_number: 19.1.0
        release_date: 2024/10/07
        reference_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/what-is-new-in-llvm-19
        rationale: LLVM 19.1.0 introduced significant performance improvements and new features tailored for Arm architectures. Notably, Arm contributed nearly 1,000 commits to this release, focusing on enhancements that optimize performance on Arm-based systems.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: The official community releases of the pre-built LLVM native toolchain for AArch64 are built and tested by Linaro and are now available on [LLVM’s GitHub](https://github.com/llvm/llvm-project/releases). The minimum version available at GitHub is v7.1.0, which has AArch64 release. Kindly refer [here](https://www.linaro.org/downloads/) for more information.

---
