---
name: Apache Kudu
category: Databases - Big-data
description: Apache Kudu is a storage system designed for fast analytics, supporting real-time data processing and seamless integration with Hadoop ecosystems.
download_url: https://kudu.apache.org/releases/
works_on_arm: true
supported_minimum_version:
    version_number: 1.13.0
    release_date: 2020/09/17
 
 
optional_info:
    homepage_url: https://kudu.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://kudu.apache.org/docs/installation.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.17.1
        release_date: 2024/12/06
        reference_content: https://github.com/apache/kudu/releases/tag/1.17.1
        rationale: This Kudu release includes multiple critical bug fixes and performance improvements. Issues causing crashes due to time synchronization, stale schemas, encryption errors, and tablet replica placement have been resolved. ARM platform stability was enhanced by fixing memory barriers and updating libunwind, particularly benefiting Graviton3. Major third-party libraries like Netty, curl, and gperftools were upgraded, addressing known vulnerabilities and improving reliability. Python client support now includes versions 3.9 and 3.10, with easier setup via auto-installing Cython. Older Python versions (3.0–3.5) are now deprecated. Additional fixes address memory leaks, race conditions, predicate pruning, and usability of altered tables.
 
optional_hidden_info:
    release_notes__supported_minimum: https://issues.apache.org/jira/browse/KUDU-3007
    release_notes__recommended_minimum:
    other_info:
 
---
