---
name: Flink
category: Databases - Big-data
description: Apache Flink is an open source stream processing framework with both batch processing and data streaming programs.
download_url: https://flink.apache.org/downloads/
works_on_arm: true
supported_minimum_version:
    version_number: 1.17.1
    release_date: 2023/05/25


optional_info:
    homepage_url: https://flink.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/flink/setup_flink/
        partner_content:
        official_docs: https://nightlies.apache.org/flink/flink-docs-stable/docs/try-flink/local_installation/
    arm_recommended_minimum_version:
        version_number: 2.0.0
        release_date: 2025/03/24
        reference_content: https://flink.apache.org/2025/03/24/apache-flink-2.0.0-a-new-era-of-real-time-data-processing/
        rationale: This release introduced Disaggregated State Management architecture, which enables more efficient resource utilization in cloud-native environments, ensuring high-performance real-time processing while minimizing resource overhead.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Pre-built binaries (wheels) are not available for Linux Arm64 systems. Installing with "pip3 install apache-flink" will first build the package from the source code. Installation and Testing is done using the released source code tar.

---
