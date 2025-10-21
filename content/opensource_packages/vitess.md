---
name: Vitess
category: Database
description: Vitess is a database clustering system for horizontal scaling of MySQL through generalized sharding.
download_url: https://github.com/vitessio/vitess/releases
works_on_arm: true
supported_minimum_version:
    version_number: 5.0.0
    release_date: 2020/01/14


optional_info:
    homepage_url: https://vitess.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://vitess.io/docs/contributing/build-on-ubuntu/
        arm_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/enabling-cloud-native-experience-across-a-diverse-and-secure-edge-ecosystem
        partner_content:
    arm_recommended_minimum_version:
        version_number: 19
        release_date: 2024/03/06
        reference_content: https://www.cncf.io/blog/2024/03/06/announcing-vitess-19/
        rationale: This version introduced several performance improvements, including a new connection pool for MySQL connections in the Tablets, which provides significantly lower query latencies and more efficient usage for idle connections. This enhancement is particularly beneficial for busy Vitess clusters with many point queries. Additionally, faster hashing in sharded Vitess clusters and faster comparisons in cross-shard aggregations were introduced, which can improve performance on Arm-based systems.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/vitessio/vitess/releases/tag/v5.0.0
    release_notes__recommended_minimum:
    other_info: Vitess release rpm and deb for AMD64 platform only. However, the project can be built from source for ARM64 from version 5.0.0 onwards.

---
