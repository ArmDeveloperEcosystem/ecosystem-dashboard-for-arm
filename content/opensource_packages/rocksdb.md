---
name: RocksDB
category: Database
description: RocksDB is a high-performance, persistent key-value store developed by Facebook. It is optimized for fast, low-latency storage systems such as solid-state drives (SSDs) and persistent memory.
download_url: https://github.com/facebook/rocksdb/releases
works_on_arm: true
supported_minimum_version:
    version_number: 6.15.2
    release_date: 2020/12/30


optional_info:
    homepage_url: https://rocksdb.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/facebook/rocksdb/blob/main/INSTALL.md
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 6.20.0
        release_date: 2022/08/08
        reference_content: https://www.alibabacloud.com/blog/flink-state---backend-improvements-and-evolution-in-2021_599218
        rationale: Version [6.20.0](https://github.com/facebook/rocksdb/releases/tag/v6.20.3) introduced performance improvements for ARM, to relax CPU for better performance. This update addressed previous limitations, enabling Flink jobs and other applications to run efficiently on Arm servers. 

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://github.com/facebook/rocksdb/releases/tag/v6.15.2).

---

