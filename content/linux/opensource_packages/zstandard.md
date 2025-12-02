---
name: Zstandard
category: Compression
description: Zstandard is a fast lossless compression algorithm, targeting real-time compression scenarios at zlib-level and better compression ratios.
download_url: https://github.com/indygreg/python-zstandard/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.16.0
    release_date: 2021/10/17


optional_info:
    homepage_url: https://github.com/indygreg/python-zstandard
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://python-zstandard.readthedocs.io/en/latest/
        arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/comparing-data-compression-algorithm-performance-on-aws-graviton2-342166113
        partner_content:
    arm_recommended_minimum_version:
        version_number: 0.22.0
        release_date: 2023/11/01
        reference_content: https://github.com/indygreg/python-zstandard/releases/tag/0.22.0
        rationale: Binary wheels for musllinux_1_1 x86_64 and Aarch64 are being built and published from this version. That means, Arm64 users on musl-based Linux distros (like Alpine) will now have much easier and faster installs of this Python package.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/indygreg/python-zstandard/releases/tag/0.16.0
    release_notes__recommended_minimum:
    other_info: The manylinux2014_aarch64 wheels are released from  0.16.0 version.
---
