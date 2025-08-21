---
name: ISA-L (Intelligent Storage Acceleration Library)
category: Storage
description: ISA-L is a collection of optimized low-level functions targeting storage applications. ISA-L includes Erasure codes, CRC, Raid, Compression, De-compression, igzip.
download_url: https://github.com/intel/isa-l/tags
works_on_arm: true
supported_minimum_version:
    version_number: 2.26.0
    release_date: 2019/03/26


optional_info:
    homepage_url: https://www.intel.com/content/www/us/en/developer/tools/isa-l/overview.html
    support_caveats:
    alternative_options: 
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://github.com/intel/isa-l/blob/master/README.md
    arm_recommended_minimum_version:
        version_number: 2.31.1
        release_date: 2025/01/09
        reference_content: https://github.com/intel/isa-l/releases/tag/v2.31.1
        rationale: This version fixed isal_deflate_icf_finish_lvl1 dispatcher, CRC compilation, and Clang compilation on igzip library on Aarch64.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: No Arm64 specific release notes are available for the initial support. Version 2.26.0 is built and tested successfully using tar file.

---
