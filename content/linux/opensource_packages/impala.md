---
name: Impala
category: Databases - Big-data
description: Apache Impala is a distributed SQL query engine designed for fast, interactive analysis of large-scale data stored in Hadoop, enabling real-time big data processing.
download_url: https://impala.apache.org/downloads.html
works_on_arm: true
supported_minimum_version:
  version_number: 4.4.0
  release_date: 2024/08/01
optional_info:
  homepage_url: https://impala.apache.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://cwiki.apache.org/confluence/display/IMPALA/Building+Impala
    arm_content:
    partner_content:
      - display_name: Microsoft Azure
        url: https://learn.microsoft.com/en-us/connectors/impala/
  arm_recommended_minimum_version:
    version_number: 4.5.0
    release_date: 2025/05/07
    reference_content: https://impala.apache.org/docs/changelog-4.5.0.html
    rationale: This version addresses several critical issues impacting ARM-based builds and tests for Impala. It resolves failures in core unit tests like TestRuntimeFilters, DataStreamTestSlowServiceQueue, and TestStatestoredHA under ARM and UBSAN environments. A hanging issue in disk-file-test and a build failure on Rocky Linux 9 ARM are also fixed.
optional_hidden_info:
  release_notes__supported_minimum: https://issues.apache.org/jira/browse/IMPALA-12353
  release_notes__recommended_minimum: null
  other_info: According to the [documentation](https://github.com/apache/impala#supported-platforms), experimental support for Linux/ARM64 is introduced in version 4.0, but Jira ticket IMPALA-12353 confirms that the proper support is added in version 4.4.0.
---
