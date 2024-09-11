---
name: Hyperscan
category: HPC
description: Hyperscan is a fast and efficient library for searching through large datasets using regular expressions. It's built for real-time text processing, handling complex pattern matching quickly.
download_url:
works_on_arm: FALSE
supported_minimum_version:
    version_number:
    release_date:
 
 
optional_info:
    homepage_url: https://www.hyperscan.io/
    support_caveats:
    alternative_options: Vectorscan
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs:
    arm_recommended_minimum_version:
        version_number:
        release_date:
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Hyperscan does not officially support the ARM64 architecture, as it is highly optimized for Intel's x86 architecture. Kindly refer to this [blog](https://developer.arm.com/documentation/109794/0100/History-of-Hyperscan) and the related [issue](https://github.com/intel/hyperscan/issues/197) for more information. However, there is an open-source alternative, Vectorscan, which is a fork of Hyperscan that has been modified to run on more platforms, including ARM64.
 
---
