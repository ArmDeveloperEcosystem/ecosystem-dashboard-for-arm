---
name: RocketMQ
category: Messaging/Comms
description: RocketMQ is a distributed platform for messaging and streaming, designed to provide high-throughput and low-latency communication, ideal for real-time processing, microservices, and event-driven architectures.
download_url: https://rocketmq.apache.org/download/
works_on_arm: true
supported_minimum_version:
  version_number: 4.9.3
  release_date: 2022/02/27
optional_info:
  homepage_url: https://rocketmq.apache.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Alibaba Cloud
        url: https://www.alibabacloud.com/blog/exploring-the-new-high-availability-design-of-rocketmq-5-0_600514
    official_docs: https://rocketmq.apache.org/docs/4.x/quickstart/01quickstart
  arm_recommended_minimum_version:
    version_number: 5.3.2
    release_date: 2025/03/08
    reference_content: https://github.com/apache/rocketmq/releases/tag/rocketmq-all-5.3.2
    rationale: This release extracted the adaptive lock mechanism, which provided performance gain on Arm CPUs by reducing CPU utilization, as discussed in this [alibabacloud blog](https://www.alibabacloud.com/blog/the-way-to-breaking-through-the-performance-bottleneck-of-locks-in-apache-rocketmq_601937).
optional_hidden_info:
  release_notes__supported_minimum: https://rocketmq.apache.org/release-notes/2022/03/04/4.9.3/
  release_notes__recommended_minimum: null
  other_info: null
---
