---
name: Libjpeg-turbo
category: Video
description: Libjpeg-turbo is a popular library for compressing JPEG images, helping to minimize the size of image data for easier storage or transmission.
download_url: https://github.com/libjpeg-turbo/libjpeg-turbo/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.3.0
    release_date: 2015/07/28


optional_info:
    homepage_url: https://libjpeg-turbo.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://libjpeg-turbo.org/Downloads/YUM
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.1.3
        release_date: 2022/02/26
        reference_content: https://github.com/libjpeg-turbo/libjpeg-turbo/releases/tag/2.1.3
        rationale: In this release, the build system now enables the intrinsics implementation of the Aarch64 NEON SIMD extensions by default when using GCC 12 or later.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and Testing are done using "apt install libjpeg-turbo8*-dev". Kindly refer [here](https://launchpad.net/ubuntu/+source/libjpeg-turbo). The minimum version of libjpeg-turbo v1.3.0 corresponds to ubuntu:14.04 and v2.1.2 to ubuntu:22.04.

---
