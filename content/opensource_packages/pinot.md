---
name: Pinot
category: Databases - Big-data
description: Apache Pinot is a real-time distributed OLAP datastore, built to deliver scalable real-time analytics with low latency.
download_url: https://pinot.apache.org/download
works_on_arm: true
supported_minimum_version:
    version_number: 0.1.0
    release_date: 2019/03/08


optional_info:
    homepage_url: https://pinot.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content: 
        official_docs: https://docs.pinot.apache.org/operators/tutorials/build-docker-images#build-image-with-arm64-base-image
    arm_recommended_minimum_version:
        version_number: 1.2.0
        release_date: 2024/08/20
        reference_content: https://docs.pinot.apache.org/basics/releases/1.2.0
        rationale: In this version, Netty arm64 dependencies were added.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: This package is platform independent, built on ARM64 as part of testing.

---
