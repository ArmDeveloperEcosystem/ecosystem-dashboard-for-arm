---
name: Apache Arrow
category: Data-format
description: Apache Arrow is a multi-language toolbox for accelerated data interchange and in-memory processing.
download_url: https://pypi.org/project/pyarrow/#files
works_on_arm: true
supported_minimum_version:
    version_number: 4.0.0
    release_date: 2021/04/26


optional_info:
    homepage_url: https://arrow.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/architectures-and-processors-blog/posts/apache-optimization-on-arm
        partner_content: 
        official_docs: https://arrow.apache.org/install/
    arm_recommended_minimum_version:
        version_number: 7.0.0
        release_date: 2022/02/08
        reference_content: https://arrow.apache.org/blog/2022/02/08/7.0.0-release/
        rationale: This version introduced Arm64 NEON SIMD optimized assembly for internal min_max utility functions, resulting in a 4x to 6x performance improvement.


optional_hidden_info:
    release_notes__supported_minimum: https://pypi.org/project/pyarrow/4.0.0/#files
    release_notes__recommended_minimum:
    other_info: This version is tested for Python only although arrow provides arm64 support for other languages as well.

---
