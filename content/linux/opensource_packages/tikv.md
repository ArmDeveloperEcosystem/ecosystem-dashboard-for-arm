---
name: TiKV
category: Database
description: A distributed transactional key-value database. Based on the design of Google Spanner and HBase.
download_url: https://github.com/tikv/tikv/releases
works_on_arm: true
supported_minimum_version:
  version_number: 5.1.0
  release_date: 2021/01/24
optional_info:
  homepage_url: https://tikv.org
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://tikv.org/docs/dev/deploy/install/install/
    arm_content:
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/startups/achieve-better-price-to-performance-for-tidb-graviton2-processors/
  arm_recommended_minimum_version:
    version_number: 6.5.1
    release_date: 2023/03/10
    reference_content: https://github.com/tikv/tikv/releases/tag/v6.5.1
    rationale: This version started supporting TiKV on a CPU with less than 1 core, increased the thread limit of the Unified Read Pool (readpool.unified.max-thread-count) to 10 times the CPU quota, to better handle high-concurrency queries.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: No ARM64 release notes are available. Installation and testing is done via tar.
---
