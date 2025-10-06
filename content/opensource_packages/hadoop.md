---
name: Hadoop
category: Databases - Big-data
description: The Apache Hadoop software library is a framework that allows for distributed processing of large data sets across clusters of computers using simple programming models.
download_url: https://hadoop.apache.org/releases.html
works_on_arm: true
supported_minimum_version:
  version_number: 3.3.0
  release_date: 2020/07/14
optional_info:
  homepage_url: https://hadoop.apache.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://hadoop.apache.org/docs/current/
    arm_content:
    partner_content:
      - display_name: Ampere
        url: https://amperecomputing.com/tuning-guides/hadoop-tuning-guide-on-bare-metal
  arm_recommended_minimum_version:
    version_number: 3.3.6
    release_date: 2023/06/23
    reference_content: https://hadoop.apache.org/release/3.3.6.html
    rationale: This version contains 117 bug fixes, improvements and enhancements, published Software Bill of Materials (SBOM) using CycloneDX Maven plugin, moved a number of HDFS-specific APIs to Hadoop Common to make it possible for certain applications that depend on HDFS semantics to run on other Hadoop compatible file systems. HDFS Router-Router Based Federation now supports storing delegation tokens on MySQL, which improves token operation through over the original Zookeeper-based implementation.
optional_hidden_info:
  release_notes__supported_minimum: https://archive.apache.org/dist/hadoop/common/hadoop-3.3.0/
  release_notes__recommended_minimum: null
  other_info: No arm64 specific release notes are available but tar file is released for ARM64 from v3.3.0 version.
---
