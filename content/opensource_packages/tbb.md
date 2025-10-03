---
name: OneTbb
category: Compilers/Tools
description: OneTBB (Threading Building Blocks) provides tools and abstractions that make it easier for developers to write parallel code in C++, without requiring deep knowledge of threading or concurrency.
download_url: https://github.com/oneapi-src/oneTBB/releases
works_on_arm: true
supported_minimum_version:
    version_number: 4.4
    release_date: 2016/09/15


optional_info:
    homepage_url: https://oneapi-src.github.io/oneTBB/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/oneapi-src/oneTBB/blob/master/INSTALL.md
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2021.9.0
        release_date: 2023/04/14
        reference_content: https://github.com/uxlfoundation/oneTBB/releases/tag/v2021.9.0
        rationale: Hybrid CPU support is a fully supported feature in this release.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and Testing are done using "apt install libtbb-dev". Kindly refer [here](https://launchpad.net/ubuntu/+source/tbb). The minimum version of tbb v4.4 corresponds to ubuntu:16.04 and v5.0 to ubuntu:22.04.

---
