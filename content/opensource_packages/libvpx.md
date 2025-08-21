---
name: Libvpx
category: Video
description: Libvpx is a free software video codec library from Google and the Alliance for Open Media (AOMedia). It serves as the reference software implementation for the VP8 and VP9 video coding formats.
download_url: https://github.com/webmproject/libvpx/tags
works_on_arm: true
supported_minimum_version:
    version_number: 1.4.0
    release_date: 2015/04/04


optional_info:
    homepage_url: https://www.webmproject.org/code/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://developer.arm.com/documentation/102651/a/Use-case--improving-VP9-performance
        partner_content:
        official_docs: https://github.com/webmproject/libvpx/blob/main/README
    arm_recommended_minimum_version:
        version_number: 1.15.0
        release_date: 2024/10/22
        reference_content: https://github.com/webmproject/libvpx/blob/main/CHANGELOG
        rationale: This version introduces several performance improvements, particularly for Arm64/Aarch64 platforms. It includes new NEON optimizations delivering 1–3% speedups for real-time (RTC) encoding and up to 7% gains for high bitdepth video-on-demand (VoD) workloads. The update also resolves numerous platform-specific issues, including build failures on Aarch64.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/webmproject/libvpx/releases/tag/v1.4.0
    release_notes__recommended_minimum:
    other_info:

---
