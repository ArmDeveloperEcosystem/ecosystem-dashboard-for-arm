---
name: Nettle
category: Crypto
description: Nettle is a cryptographic library focused on low-level operations for secure applications. It implements cryptographic algorithms such as AES, RSA, and SHA, supporting symmetric and public-key encryption methods.
download_url: https://ftp.gnu.org/gnu/nettle/
works_on_arm: true
supported_minimum_version:
    version_number: 3.1
    release_date: 2015/04/07


optional_info:
    homepage_url: https://www.lysator.liu.se/~nisse/nettle/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://git.lysator.liu.se/nettle/nettle/-/blob/master/README?ref_type=heads
    arm_recommended_minimum_version:
        version_number: 3.8
        release_date: 2022/06/03
        reference_content: https://github.com/gnutls/nettle/blob/master/ChangeLog
        rationale: This release adds optimized implementations for AES (128/192/256), Chacha, SHA1, and SHA256, along with extended fat build support for Arm64 to enable runtime CPU feature detection. The GCM implementation was refactored with new GHASH set-key and update routines, providing better performance and maintainability on Armv8. These enhancements significantly improve cryptographic efficiency on Arm64 platforms, benefiting workloads that rely on AES-GCM, Chacha, and SHA-2 primitives.

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Linux/Arm64 release notes are not available. Installation and testing are done via the tar archive [3.1](https://ftp.gnu.org/gnu/nettle/nettle-3.1.tar.gz).

---
