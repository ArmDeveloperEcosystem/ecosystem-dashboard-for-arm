---
name: Memcached
category: Databases - noSQL
description: Memcached is a high performance multithreaded event-based key/value cache store intended to be used in a distributed system.
download_url: https://memcached.org/downloads
works_on_arm: true
supported_minimum_version:
  version_number: 1.5.16
  release_date: 2019/05/25
optional_info:
  homepage_url: https://memcached.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://github.com/memcached/memcached/wiki
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/memcached-benchmarking-aws-graviton2-50-p-p-gains
    partner_content:
      - display_name: Ampere
        url: https://amperecomputing.com/tuning-guides/memcached-tuning-guide
  arm_recommended_minimum_version:
    version_number: 1.6.28
    release_date: 2024/05/31
    reference_content: https://github.com/memcached/memcached/wiki/ReleaseNotes1628
    rationale: This version fixes unfortunate potentially critical use-after-free bug in the proxy mode that was introduced in 1.6.27. Also adds experimental support for TLS to proxy backends.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/memcached/memcached/wiki/ReleaseNotes145#fixes
  release_notes__recommended_minimum: null
  other_info: null
---
