---
name: Libunwind
category: Compilers/Tools
description: libunwind is a library that enables programs to inspect and manipulate call stacks, supporting stack unwinding for debugging, profiling, and exception handling across multiple CPU architectures.
download_url: https://github.com/libunwind/libunwind/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.2
    release_date: 2017/01/28


optional_info:
    homepage_url: http://www.nongnu.org/libunwind/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/libunwind/libunwind#general-build-instructions
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: A patch from Linaro [Patchwork](https://patches.linaro.org/project/oe-core/patch/1411725589-20460-1-git-send-email-fathi.boudra@linaro.org/) explicitly adds support for AArch64, and the GitHub release of libunwind version [1.2](https://github.com/libunwind/libunwind/releases/tag/v1.2) indicates that patches related to the Linux/AArch64 platform are included.

---
