---
name: Lz4
category: Compression
description: LZ4 is lossless compression algorithm, providing compression speed > 500 MB/s per core, scalable with multi-cores CPU.
download_url: https://github.com/lz4/lz4/releases
works_on_arm: true
supported_minimum_version:
    version_number: r116
    release_date: 2014/04/10


optional_info:
    homepage_url: http://www.lz4.org
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:  
        official_docs: https://github.com/lz4/lz4/blob/dev/README.md
    arm_recommended_minimum_version:
        version_number: 1.9.4
        release_date: 2022/08/16
        reference_content: https://github.com/lz4/lz4/releases/tag/v1.9.4
        rationale: In this version, decompression performance on high-end ARM64 platforms, such as Apple's M1 and server-class CPUs, has improved by 20%, particularly when using GCC. For data compressed with -BD4 settings, decompression speed is boosted by 70%, especially in block-by-block scenarios like the LZ4 CLI. Additionally, skipping checksum validation in LZ4 frame decompression can further improve speed by 40%, now supported at both CLI (--no-crc) and library levels.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum: 
    other_info: There are no release notes or binaries released for ARM64. However, lz4 can be built on ARM64 from the first version(r116).

---
