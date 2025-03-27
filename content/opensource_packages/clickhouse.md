---
name: Clickhouse
category: Database
description: ClickHouse is a high-performance, column-oriented SQL database management system (DBMS) for online analytical processing (OLAP).
download_url: https://github.com/ClickHouse/ClickHouse/releases
works_on_arm: true
supported_minimum_version:
    version_number: 22.1
    release_date: 2022/01/18


optional_info:
    homepage_url: https://clickhouse.com/docs/en/intro
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/clickhouse/
        partner_content:
        official_docs: https://clickhouse.com/docs/en/development/build-cross-arm
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum: https://clickhouse.com/docs/en/whats-new/changelog/2022#buildtestingpackaging-improvement-11
    release_notes__recommended_minimum:
    other_info: The support for cross-compiling to the CPU architecture AARCH64 was added in version 19.17.4.11, as mentioned [here](https://clickhouse.com/docs/en/whats-new/changelog/2019#buildtestingpackaging-improvement). However, ARM64 binaries are released at GitHub releases from version v22.3.7.28-lts onwards. Kindly refer [here](https://github.com/ClickHouse/ClickHouse/releases/tag/v22.3.7.28-lts). Also, on the official clickhouse website, it's mentioned in the changelogs of v22.1 that this version adds packages, functional tests and Docker builds for AArch64. Kindly refer [here](https://clickhouse.com/docs/en/whats-new/changelog/2022#buildtestingpackaging-improvement-11).

---
