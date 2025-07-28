---
name: xxHash
category: Storage
description: xxHash is an extremely fast non-cryptographic hash algorithm, working at RAM speed limit. It is proposed in four flavors (XXH32, XXH64, XXH3_64bits and XXH3_128bits). 
download_url: https://pypi.org/project/xxhash/#files
works_on_arm: true
supported_minimum_version:
    version_number: 1.4.4
    release_date: 2020/06/20


optional_info:
    homepage_url: https://xxhash.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/ifduyue/python-xxhash#installation
    arm_recommended_minimum_version:
        version_number: 3.1.0
        release_date: 2022/10/19
        reference_content: https://github.com/ifduyue/python-xxhash/releases/tag/v3.1.0
        rationale: Wheels for musllinux are being built and published (for many platforms including AArch64) from this version. That means, Arm64 users on musl-based Linux distros (like Alpine) will now have much easier and faster installs of xxHash.


optional_hidden_info:
    release_notes__supported_minimum: https://pypi.org/project/xxhash/1.4.4/#files
    release_notes__recommended_minimum:
    other_info: There are no release notes for Arm64. However, AArch64 binaries are published from 1.4.4 release.
---

