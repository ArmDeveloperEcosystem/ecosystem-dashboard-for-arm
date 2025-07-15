---
name: VVenC
category: Video
description: VVenC software is based on VTM 6, with optimizations including software redesign to mitigate performance bottlenecks and extensive SIMD optimizations.
download_url: https://github.com/fraunhoferhhi/vvenc/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.7.0-rc1
    release_date: 2022/12/05


optional_info:
    homepage_url: https://www.hhi.fraunhofer.de/en/departments/vca/technologies-and-solutions/h266-vvc/fraunhofer-versatile-video-encoder-vvenc.html
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/vvenc/vvenc/
        partner_content:
        official_docs: https://github.com/fraunhoferhhi/vvenc/wiki/Build
    arm_recommended_minimum_version:
        version_number: 1.13.0
        release_date: 2024/12/13
        reference_content: https://github.com/fraunhoferhhi/vvenc/blob/master/changelog.txt
        rationale: This version introduced many ARM SIMD optimizations for both NEON and SVE. The details can be viewed in the [PR for 1.13.0-rc1](https://github.com/fraunhoferhhi/vvenc/pull/486/files).

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the tar.

---
