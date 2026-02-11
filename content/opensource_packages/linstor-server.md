---
name: Linstor-server
category: Storage
description: LINSTOR is open-source software that manages replicated volumes across a group of machines, and it natively integrates with Kubernetes and other platforms, making the build, run, and controlling block storage simple.
download_url: https://github.com/LINBIT/linstor-server/tags
works_on_arm: true
supported_minimum_version:
    version_number: Master branch
    release_date: 2024/11/18


optional_info:
    homepage_url: https://github.com/LINBIT/linstor-server
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/LINBIT/linstor-server?tab=readme-ov-file#building
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Only the master branch builds successfully from source on both Linux ARM64 and AMD64 with JDK17. Other released tags fail to build from source on both platforms. There are no Linux/ARM64 specific release notes.

---
