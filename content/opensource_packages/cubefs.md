---
name: CubeFS
category: Containers and Orchestration
description: CubeFS is a new generation cloud-native storage that supports access protocols such as S3, HDFS, and POSIX.
download_url: https://cubefs.io/download
works_on_arm: true
supported_minimum_version:
    version_number: 2.2.0
    release_date: 2020/09/04


optional_info:
    homepage_url: https://cubefs.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/cubefs/cubefs/blob/master/INSTALL.md
    arm_recommended_minimum_version:
        version_number: 3.4.0-beta-rdma
        release_date: 2024/11/18
        reference_content: https://github.com/cubefs/cubefs/releases/tag/v3.4.0-beta_rdma
        rationale: This beta release introduces RDMA support based on version 3.4.0. The client can now enable RDMA via configuration and supports sending triple copies for traffic under 300MB/s. DataNode and MetaNode both accept RDMA and TCP requests (except Raft traffic on MetaNode). FIO direct I/O performance sees a 30% boost. Key RDMA-related bugs and enhancements were also addressed.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/cubefs/cubefs/releases/tag/v2.2.0
    release_notes__recommended_minimum:
    other_info:

---
