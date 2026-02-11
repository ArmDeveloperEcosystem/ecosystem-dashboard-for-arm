---
name: Kafka
category: Databases - noSQL
description: Kafka is an event streaming platform. It is a distributed system consisting of servers and clients that communicate via a high-performance TCP network protocol.
download_url: https://kafka.apache.org/downloads
works_on_arm: true
supported_minimum_version:
  version_number: 3.4.1
  release_date: 2023/06/06
optional_info:
  homepage_url: https://kafka.apache.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://github.com/apache/kafka?tab=readme-ov-file#apache-kafka
    arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/kafka/
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/developer/tuning-apache-kafka-and-confluent-platform-for-graviton2-using-amazon-corretto/
  arm_recommended_minimum_version:
    version_number: 3.5.0
    release_date: 2023/06/15
    reference_content: https://kafka.apache.org/blog#apache_kafka_350_release_announcement
    rationale: Kafka 3.5.0 includes a significant number of new features and fixes, including improing Kafka Connect and MirrorMaker 2. They aren't ARM specific, but can benefit all architectures, including Linux/ARM64.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: Linux/ARM64 release notes are not available. Installation and testing are done using released source code tar.
---
