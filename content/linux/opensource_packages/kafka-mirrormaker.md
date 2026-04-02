---
name: Kafka MirrorMaker
category: Messaging/Comms
description: Kafka MirrorMaker is a tool within Apache Kafka used to replicate data (topics, configurations, and consumer offsets) between Kafka clusters, typically for use cases such as geo-replication, disaster recovery, and data migration.
download_url: https://kafka.apache.org/downloads
works_on_arm: true
supported_minimum_version:
    version_number: 3.4.1
    release_date: 2023/06/06
 
 
optional_info:
    homepage_url: https://kafka.apache.org/
    support_caveats: Kafka MirrorMaker is a component within the Apache Kafka distribution rather than an independent project. Given that Apache Kafka (≥ 3.4.1) has already been validated to build and run on Linux/Arm64 (as reflected in the Ecosystem Dashboard), Kafka MirrorMaker is also expected to work on Arm64, as it relies on the same JVM-based runtime and codebase.
    alternative_options:
    getting_started_resources:
        official_docs: https://kafka.apache.org/42/configuration/mirrormaker-configs/
        arm_content:
        partner_content:
          - display_name: Amazon AWS
            url: https://aws.amazon.com/blogs/big-data/use-msk-connect-for-managed-mirrormaker-2-deployment-with-iam-authentication/
    arm_recommended_minimum_version:
        version_number: 3.5.0
        release_date: 2023/06/15
        reference_content: https://kafka.apache.org/blog#apache_kafka_350_release_announcement
        rationale: Kafka 3.5.0 includes a significant number of new features and fixes, including improing Kafka Connect and MirrorMaker 2. They aren't ARM specific, but can benefit all architectures, including Linux/Arm64.
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info:
 
---
