---
name: Apache Pulsar
category: Messaging/Comms
description: Apache Pulsar is an open-source, distributed messaging and streaming platform built for the cloud.
download_url: https://pulsar.apache.org/download/
works_on_arm: true
supported_minimum_version:
    version_number: 2.10.0
    release_date: 2022/04/13


optional_info:
    homepage_url: https://pulsar.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/apache/pulsar?tab=readme-ov-file#build-pulsar
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.0.0
        release_date: 2023/05/02
        reference_content: https://pulsar.apache.org/blog/2023/05/02/announcing-apache-pulsar-3-0/
        rationale: This version is the first Long-Term Support (LTS) version, with over 140 contributors submitting about 1500 commits for feature enhancements and bug fixes. It introduced new Pulsar broker load balancer, Large-scale delayed message support, build for multi-arch docker images including Arm64, Blue-green cluster deployment support, etc.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 specific release notes for apache pulsar are not found. The least version that built successfully on the Neoverse N1 is 2.10.0. However, pulsar's client (client cpp) has ARM64 support mentioned in it's [release notes](https://pulsar.apache.org/release-notes/versioned/client-cpp-2.10.0/) in version 2.10.0.

---
