---
name: Zlib
category: Compression
description: Zlib is a general purpose data compression library.
download_url: https://github.com/madler/zlib/releases
works_on_arm: true
supported_minimum_version:
  version_number: 1.2.12
  release_date: 2022/03/27
optional_info:
  homepage_url: http://zlib.net/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/zlib
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/opensource/improving-zlib-cloudflare-and-comparing-performance-with-other-zlib-forks/
    official_docs: null
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: http://zlib.net/ChangeLog.txt
  release_notes__recommended_minimum: null
  other_info: Version 1.2.12 adds the use of ARMv8 crc32 instructions when requested, and uses ARM crc32 instructions if the ARM architecture has them.
---
