---
name: Kyuubi
category: Containers and Orchestration
description: Kyuubi is a distributed SQL engine designed for large-scale data processing, offering high-performance and easy-to-use analytics on top of Apache Spark. It simplifies the management and execution of complex SQL queries in big data environments.
download_url: https://github.com/apache/kyuubi/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.5.0-incubating
    release_date: 2022/03/16

optional_info:
    homepage_url: https://kyuubi.readthedocs.io/en/master/index.html
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://kyuubi.readthedocs.io/en/master/quick_start/quick_start.html#installation
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.10.0
        release_date: 2024/10/27
        reference_content: https://kyuubi.apache.org/release/1.10.0.html
        rationale: This release ensures full compatibility with Java 8, 11, and 17, and Scala 2.12/2.13. It supports Apache Spark 3.2 to 3.5 (with 3.2 deprecated) and Apache Flink 1.17 to 1.20. Users can now create batch jobs by uploading extra resources via the REST API. A new server selection strategy has been added for HA mode. The Spark JVM quake plugin is introduced, along with periodic cleanup of expired temp files and logs. Performance has also been enhanced through deduplication of Ranger access requests in the AuthZ plugin.


optional_hidden_info:
    release_notes__supported_minimum: https://kyuubi.apache.org/release/1.5.0-incubating.html
    release_notes__recommended_minimum:
    other_info: Support for ARM64-Graviton2 was introduced in the CI starting from v1.5.0-incubating, enabling build and test processes on Linux/ARM64.

---
