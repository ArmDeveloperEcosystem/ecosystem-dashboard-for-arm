---
name: Android-Cuttlefish
category: Miscellaneous
description: Cuttlefish is a configurable Android Virtual Device (AVD) that runs both remotely and locally, and it also guarantees full fidelity with Android framework.
download_url: https://github.com/google/android-cuttlefish/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.9.26
    release_date: 2024/05/21


optional_info:
    homepage_url: https://source.android.com/docs/devices/cuttlefish
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://source.android.com/docs/devices/cuttlefish/get-started
    arm_recommended_minimum_version:
        version_number: 1.12.0
        release_date: 2025/06/19
        reference_content: https://github.com/google/android-cuttlefish/releases/tag/v1.12.0
        rationale: In this version, cuttlefish has added initial support for compiling libffi on Arm64 by including required headers and platform selection options, enabling native builds and execution on Arm-based systems.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/google/android-cuttlefish/tree/v0.9.26#virtual-device-for-android-host-side-utilities
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 support is mentioned in the Readme.md in the first released version on GitHub, i.e 0.9.26.

---
