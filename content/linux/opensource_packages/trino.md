---
name: Trino
category: Databases - Big-data
description: Trino is a distributed SQL query engine that enables fast querying of large datasets across various data sources.
download_url: https://trino.io/download
works_on_arm: true
supported_minimum_version:
    version_number: 330
    release_date: 2020/02/18
 
 
optional_info:
    homepage_url: https://trino.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://trino.io/docs/current/installation.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 381
        release_date: 2022/05/16
        reference_content: https://trino.io/docs/current/release/release-381.html#docker-image
        rationale: This version improved Advanced Encryption Standard (AES) processing performance on ARM64 processors. This feature is useful for operations such as accessing object storage systems via TLS/SSL.
 
optional_hidden_info:
    release_notes__supported_minimum: https://trino.io/docs/current/release/release-330.html#:~:text=Add%20experimental%20support%20for%20running%20on%20Linux%20aarch64%20(ARM64)
    release_notes__recommended_minimum:
    other_info: From [this issue](https://github.com/trinodb/trino/issues/2262), it is clear that AArch64 support has been added since release 330.
 
---
