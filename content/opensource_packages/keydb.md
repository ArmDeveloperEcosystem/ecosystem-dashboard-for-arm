---
name: KeyDB
category: Databases - noSQL
description: KeyDB is a high performance open source database used at Snap, and a powerful drop-in alternative to Redis.
download_url: https://github.com/Snapchat/KeyDB/releases
works_on_arm: true
supported_minimum_version:
  version_number: 6.3.0
  release_date: 2022/05/12
optional_info:
  homepage_url: https://docs.keydb.dev/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/aws/new-m6g-ec2-instances-powered-by-arm-based-aws-graviton2/
    official_docs: https://docs.keydb.dev/blog/2020/03/02/blog-post/
  arm_recommended_minimum_version:
    version_number: 6.3.3
    release_date: 2023/05/03
    reference_content: https://docs.keydb.dev/news/2023/05/02/release_6_3_3/
    rationale: This version updates keydb's supported Linux distributions and base images to better support KeyDB FLASH & C++17 features. The release includes updates to the KeyDB FLASH feature, such as updating RocksDB to v7.9.2 and fixing race conditions in prefetching keys asynchronously. These improvements can enhance the performance and stability of KeyDB when using FLASH storage.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/Snapchat/KeyDB/releases/tag/v6.3.0
  release_notes__recommended_minimum: null
  other_info: KeyDB was made open source from version 6.3.0 which was released on May 12, 2022. However, the ARM support was first added in the version [0.9.3](https://github.com/Snapchat/KeyDB/releases/tag/v0.9.3) which was released on March 25, 2019.
---
