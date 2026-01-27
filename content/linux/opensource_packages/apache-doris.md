---
name: Apache Doris
category: Database
description: Apache Doris is a modern data warehouse for real-time analytics. It delivers lightning-fast analytics on real-time data at scale.
download_url: https://doris.apache.org/download
works_on_arm: true
supported_minimum_version:
    version_number: 1.2.1
    release_date: 2022/12/31


optional_info:
    homepage_url: https://doris.apache.org
    support_caveats: Note that a more optimized Apache Doris across architectures is available from version 2.1.6, released 2024/09/10, and 3.0.
    alternative_options:
    getting_started_resources:
        official_docs: https://doris.apache.org/docs/gettingStarted/quick-start
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.0.0
        release_date: 2024/07/22
        reference_content: https://doris.apache.org/docs/releasenotes/v3.0/release-3.0.0
        rationale: This version supports a compute-storage decoupled mode in addition to the compute-storage coupled mode for cluster deployment. Hence, users can achieve physical isolation between query loads across multiple compute clusters, as well as isolation between read and write loads. Additionally, users can take advantage of low-cost shared storage systems such as object storage or HDFS to significantly reduce storage costs.


optional_hidden_info:
    release_notes__supported_minimum: https://doris.apache.org/docs/releasenotes/v1.1/release-1.1.0
    release_notes__recommended_minimum: 
    other_info: Apache Doris performance on arm has improved dramatically since version 2.1, the latest versions of 2.1 and 3.0 are recommended. See release notes [here](https://doris.apache.org/docs/releasenotes/v2.1/release-2.1.6).
---
