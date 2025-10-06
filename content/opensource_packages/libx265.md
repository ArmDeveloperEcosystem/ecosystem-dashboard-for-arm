---
name: libx265
category: Video
description: libx265 is an encoder for creating digital video streams in the High Efficiency Video Coding (HEVC/H. 265) video compression format.
download_url: https://bitbucket.org/multicoreware/x265_git/downloads/?tab=tags
works_on_arm: true
supported_minimum_version:
  version_number: 3.4
  release_date: 2020/05/29
optional_info:
  homepage_url: https://www.videolan.org/developers/x265.html
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://bitbucket.org/multicoreware/x265_git/wiki/Home
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/reduce-h-265-high-res-encoding-costs-by-over-80-with-aws-graviton2-1207706725
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/opensource/video-encoding-on-graviton-in-2025/
      - display_name: Ampere
        url: https://amperecomputing.com/tuning-guides/FFmpeg-Tuning-Guide
  arm_recommended_minimum_version:
    version_number: 3.6
    release_date: 2024/04/04
    reference_content: https://x265.readthedocs.io/en/master/releasenotes.html#version-3-6
    rationale: This version introduced Arm64 NEON optimizations, with several performance-critical C functions rewritten for AArch64. These changes delivered ~20% overall performance improvement.
optional_hidden_info:
  release_notes__supported_minimum: https://x265.readthedocs.io/en/master/releasenotes.html#version-3-4
  release_notes__recommended_minimum: null
  other_info: No ARM64 specific release notes and binaries are available. Building it from source.
---
