---
name: Hive
category: Databases - Big-data
description: The Apache Hive data warehouse software helps to read, write, and manage large datasets that reside in the distributed storage using SQL.
download_url: https://hive.apache.org/general/downloads/
works_on_arm: true
supported_minimum_version:
  version_number: 4.0.0-alpha-2
  release_date: 2022/11/16
optional_info:
  homepage_url: https://hive.apache.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://cwiki.apache.org/confluence/display/Hive/GettingStarted
    arm_content: https://community.arm.com/arm-community-blogs/b/ai-and-ml-blog/posts/how-to-build-scalable-next-best-action-solution-in-pure-sql-with-hivemall
    partner_content:
  arm_recommended_minimum_version:
    version_number: 4.0.0
    release_date: 2024/04/30
    reference_content: https://news.apache.org/foundation/entry/apache-software-foundation-announces-apache-hive-4-0
    rationale: This version introduces several major enhancements aimed at improving performance, scalability, and ease of deployment. It features native integration with Apache Iceberg for efficient table management, along with enhanced ACID compliance through improved transaction and locking mechanisms. New compaction features for both Hive ACID and Iceberg tables optimize storage usage. The release also adds support for materialized views to accelerate query performance, runtime optimizations in Apache Tez and Hive LLAP for faster data processing, and enhanced replication for both external and ACID tables. Additionally, Hive 4.0 supports integration with Apache Ozone, enabling scalable and efficient object storage solutions.
optional_hidden_info:
  release_notes__supported_minimum: https://issues.apache.org/jira/secure/ReleaseNote.jspa?version=12351489&styleName=Html&projectId=12310843
  release_notes__recommended_minimum: null
  other_info: null
---
