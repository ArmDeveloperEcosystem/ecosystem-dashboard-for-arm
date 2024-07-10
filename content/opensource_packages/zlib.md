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
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/zlib
        partner_content: https://aws.amazon.com/blogs/opensource/improving-zlib-cloudflare-and-comparing-performance-with-other-zlib-forks
        official_docs:
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum: http://zlib.net/ChangeLog.txt
    release_notes__recommended_minimum:
    other_info: Version 1.2.12 adds the use of ARMv8 crc32 instructions when requested, and uses ARM crc32 instructions if the ARM architecture has them.

---
