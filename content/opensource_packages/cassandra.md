---
name: Cassandra
category: Databases - noSQL
description: Apache Cassandra is an open-source, distributed NoSQL database designed to handle massive volumes of data on a highly scalable and highly available platform.
download_url: https://cassandra.apache.org/_/download.html
works_on_arm: true
supported_minimum_version:
    version_number: 3.0.14
    release_date: 2017/10/04


optional_info:
    homepage_url: https://cassandra.apache.org/_/index.html
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/increase-price_2d00_performance-by-deploying-cassandra-on-aws-graviton2
        partner_content: https://amperecomputing.com/solution/cassandra
        official_docs: https://cassandra.apache.org/doc/latest/cassandra/getting-started/index.html
    arm_recommended_minimum_version:
        version_number: 5.0.0
        release_date: 2024/09/05
        reference_content: https://cassandra.apache.org/_/blog/Apache-Cassandra-5.0-Announcement.html
        rationale: Apache Cassandra 5.0 is a major release introducing significant performance, usability, and scalability enhancements. Key features include Storage Attached Indexes (SAI) for flexible querying, Trie-based memtables/SSTables for better efficiency, and the Unified Compaction Strategy (UCS) for automated data management. It also supports JDK 17 for up to 20% performance gains and adds vector search for AI applications. The release marks the end-of-life for the 3.x series, urging users to upgrade for continued support.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Platform independent binaries are released for all the architecture. To install minimum version of Cassandra java 8 is needed and to use the CQL shell cqlsh, install the python 2.7.
---
