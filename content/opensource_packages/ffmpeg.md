---
name: FFmpeg
category: Video
description: FFmpeg is an open-source software project consisting of a suite of libraries and programs for handling video, audio, and other multimedia files and streams.
download_url: https://ffmpeg.org/download.html
works_on_arm: true
supported_minimum_version:
  version_number: n0.7.7
  release_date: 2011/11/05
optional_info:
  homepage_url: https://ffmpeg.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://community.arm.com/arm-community-blogs/b/graphics-gaming-and-vr-blog/posts/quick-tips-use-ffmpeg-to-convert-pictures-to-raw-rgb565
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/opensource/optimized-video-encoding-with-ffmpeg-on-aws-graviton-processors/
    official_docs: https://ffmpeg.org/ffmpeg.html
  arm_recommended_minimum_version:
    version_number: 5.2
    release_date: 2022/11/15
    reference_content: https://aws.amazon.com/blogs/opensource/optimized-video-encoding-with-ffmpeg-on-aws-graviton-processors/
    rationale: This blog shows a benchmark of FFmpeg video encoding on Graviton processors, delivering around 60% performance boost vs other architectures.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: The first version after the release of AArch64 that can be built on ARM is n0.7.7 version.
---
