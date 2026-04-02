---
name: Apache Iceberg
category: Data-format
description: Iceberg is an open table format for large analytic datasets that enables compute engines to work with data like SQL tables, supporting features such as schema evolution, partitioning, and time travel.
download_url: https://github.com/apache/iceberg/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.1.0
    release_date: 2022/11/28
 
 
optional_info:
    homepage_url: https://iceberg.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://iceberg.apache.org/docs/nightly/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.8.0
        release_date: 2025/02/13
        reference_content: https://github.com/apache/iceberg/releases/tag/apache-iceberg-1.8.0
        rationale: In this release, docker build for Arm64 was added.
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Release notes for the initial Linux/Arm64 support isn't available. Version 1.1.0 can be built from source via "./gradlew build -x test -x integrationTest" and JDK version 11.
 
---
