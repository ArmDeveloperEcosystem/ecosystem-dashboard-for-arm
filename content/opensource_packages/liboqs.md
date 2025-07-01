---
name: LibOQS
category: Crypto
description: Liboqs is an open source C library for quantum-safe cryptographic algorithms.
download_url: https://github.com/open-quantum-safe/liboqs/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.7.1
    release_date: 2021/12/17


optional_info:
    homepage_url: https://openquantumsafe.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/open-quantum-safe/liboqs/wiki/Platform-specific-notes-for-building-liboqs#benchmarking-on-armv8
    arm_recommended_minimum_version:
        version_number: 0.13.0
        release_date: 2025/04/17
        reference_content: https://github.com/open-quantum-safe/liboqs/releases/tag/0.13.0
        rationale: This version updates the default ML-KEM implementation to PQCP's mlkem-native, offering Portable C, AVX2, and AArch64 variants. These implementations are formally verified for memory safety (via CBMC) and functional correctness (via HOL-Light for AArch64). Additionally, support has been added for the public Ubuntu 24.04 ARM GitHub Actions runner.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/open-quantum-safe/liboqs/releases/tag/0.7.1
    release_notes__recommended_minimum:
    other_info: Release notes in version 0.7.1 have included ARM64 optimizations. This version gets built successfully on the Neoverse N1. Before v0.7.1, build failed on both AMD64 and ARM64 platforms.

---
