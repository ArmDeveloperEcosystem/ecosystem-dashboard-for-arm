---
name: LightGBM
category: AI/ML
description: LightGBM is a free and open-source distributed gradient-boosting framework for machine learning that uses tree based learning algorithms.
download_url: https://github.com/microsoft/LightGBM/releases
works_on_arm: true
supported_minimum_version:
    version_number: 3.2.0
    release_date: 2021/03/22


optional_info:
    homepage_url: https://lightgbm.readthedocs.io/en/latest/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://lightgbm.readthedocs.io/en/latest/Installation-Guide.html
        arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/xgboost-lightgbm-aws-graviton3
        partner_content:
    arm_recommended_minimum_version:
        version_number: 4.0.0
        release_date: 2023/07/14
        reference_content: https://github.com/microsoft/LightGBM/releases/tag/v4.0.0
        rationale: This release contains all previously-unreleased changes since v3.3.1 over 1.5 years ago, including support for C++17, added quantized training, fixed DEBUG-mode GPU builds, etc.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/microsoft/LightGBM/releases/tag/v3.2.0
    release_notes__recommended_minimum:
    other_info: The Project releases only python wheels for aarch64. No other executables are being released for aarch64.
---
