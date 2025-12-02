---
name: TimescaleDB
category: Databases - noSQL
description: TimescaleDB is an open-source time-series database that allows users to store and analyze large amounts of time-stamped data with high performance and scalability.
download_url: https://github.com/timescale/timescaledb/releases
works_on_arm: true
supported_minimum_version:
    version_number: v2.6.0
    release_date: 2022/02/23


optional_info:
    homepage_url: https://github.com/timescale/timescaledb/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/timescale/timescaledb/blob/main/docs/BuildSource.md
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.16.0
        release_date: 2024/07/31
        reference_content: https://github.com/timescale/timescaledb/releases/tag/2.16.0
        rationale: This version introduced multiple performance focused optimizations for data manipulation operations (DML) over compressed chunks, which improved upsert performance by more than 100x in some cases and more than 1000x in some update/delete scenarios.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: No arm64 specific release notes are available. Installation and testing was done through tar file.

---
