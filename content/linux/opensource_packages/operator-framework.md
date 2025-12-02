---
name: operator-framework
category: Miscellaneous
description: operator-framework is a SDK for building Kubernetes applications.
download_url: https://github.com/operator-framework/operator-sdk/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.17.0
    release_date: 2020/04/16


optional_info:
    homepage_url: https://sdk.operatorframework.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://sdk.operatorframework.io/docs/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.24.0
        release_date: 2022/10/11
        reference_content: https://github.com/operator-framework/operator-sdk/releases/tag/v1.24.0
        rationale: This version introduces plugin updates and key bug fixes, adds support for test selectors in scorecard-kuttl, enabling more granular test execution via config-based selectors. Notably, operator-sdk run bundle now correctly handles channel mismatches and prevents upgrade stalling. A critical enhancement for Arm support adds logic to convert aarch64 to arm64 in Ansible and Helm operator Makefiles, improving binary download compatibility on Arm-based systems.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/operator-framework/operator-sdk/releases/tag/v0.17.0
    release_notes__recommended_minimum:
    other_info:

---
