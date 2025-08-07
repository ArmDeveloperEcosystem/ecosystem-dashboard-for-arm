---
name: Freedesktop-SDK
category: Operating System
description: Freedesktop-sdk is a comprehensive development kit designed to provide a consistent and reliable base runtime and build environment for developing and deploying applications on Linux-based operating systems.
download_url: https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/tags
works_on_arm: true
supported_minimum_version:
    version_number: freedesktop-sdk-18.08.0
    release_date: 2018/08/09


optional_info:
    homepage_url: https://freedesktop-sdk.gitlab.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:  
        partner_content: 
        official_docs: https://freedesktop-sdk.gitlab.io/documentation/getting-started/
    arm_recommended_minimum_version:
        version_number: freedesktop-sdk-25.08beta.1
        release_date: 2025/06/25
        reference_content: https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/master/NEWS.yml
        rationale: Several AArch64-specific enhancements were introduced in this version to improve build and runtime support. Assembly optimizations were enabled for libx265 on AArch64, ensuring performance parity with x86_64. Certain build flags were adjusted, including the disabling of gcs on AArch64 and the enabling of Pointer Authentication for improved security. In webrtc-audio-processing, NEON optimizations were selectively disabled on all platforms except AArch64, preserving performance where relevant. Continuous integration saw improvements with the inclusion of minimal systemd VM jobs for AArch64 (allowed to fail gracefully), and cleanup efforts removed redundant packaging steps such as duplicate manual publishing and unnecessary AArch64 compatibility runtime copying for x86_64. Additionally, support for the x86_64 to AArch64 Flatpak cross-toolchain was dropped, streamlining the build pipeline.

optional_hidden_info:
    release_notes__supported_minimum: https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/blob/master/NEWS.yml
    release_notes__recommended_minimum: 
    other_info: Version 18.08.0 introduces native support for multi-architecture builds, including AArch64, through enhanced GitLab CI capabilities.

---
