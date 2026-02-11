---
name: Aerospike
category: Databases - noSQL
description: Aerospike is a distributed NoSQL database that offers fast read/writes and uptimes.
download_url: https://aerospike.com/download/
works_on_arm: true
supported_minimum_version:
    version_number: 6.2
    release_date: 2022/11/17


optional_info:
    homepage_url: https://aerospike.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://aerospike.com/docs/server/operations/install/linux/ubuntu
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 6.3
        release_date: 2023/03/21
        reference_content: https://aerospike.com/blog/aerospike-database-6-3-smoother-operations-at-scale/
        rationale: This version enhances Arm64 support with LuaJIT reintroduced, improving UDF performance on Arm servers. However, it also brings breaking changes - support for Debian 10 on Arm64 is discontinued, and Ubuntu 18.04 is removed across all platforms.

optional_hidden_info:
    release_notes__supported_minimum: https://aerospike.com/docs/reference/release_notes/server/6.2-server-release-notes
    release_notes__recommended_minimum:
    other_info:

---
