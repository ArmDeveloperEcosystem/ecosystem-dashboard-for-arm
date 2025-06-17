---
name: Flume
category: Databases - Big-data
description: Flume is a distributed, reliable, and available service for efficiently collecting, aggregating, and moving large amounts of log data.
download_url: https://flume.apache.org/download.html
works_on_arm: true
supported_minimum_version:
    version_number: 1.10.0
    release_date: 2022/06/13


optional_info:
    homepage_url: https://flume.apache.org/
    support_caveats: 
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://flume.apache.org/releases/content/1.10.0/FlumeUserGuide.html
    arm_recommended_minimum_version:
        version_number: 1.11.0
        release_date: 2022/10/10
        reference_content: https://flume.apache.org/releases/1.11.0.html
        rationale: This version introduces Spring Boot support for easier deployment and integration into modern Java ecosystems. Kafka capabilities are enhanced with support for timestamps and headers in KafkaSink, and hostname verification can now be disabled for SSL-encrypted Kafka communication. Security and configuration validation are improved through stricter checks (e.g., providerUrl). The release also includes dependency upgrades to Maven Jar Plugin 3.2.2, Scala 2.13.9, and Gson 2.9.1, ensuring improved stability and compatibility with modern build environments. It is to be noted that apache flume is not maintained anymore.

optional_hidden_info:
    release_notes__supported_minimum: https://flume.apache.org/releases/1.10.0.html
    release_notes__recommended_minimum:
    other_info: 

---

