---
name: Solr 
category: Content mgmt platforms
description: Solr is an open-source platform that provides full-text search, faceted search, real-time indexing, dynamic clustering, database integration, and rich document-handling capabilities. 
download_url: https://github.com/apache/solr/tags
works_on_arm: true
supported_minimum_version:
    version_number: 9.1.0
    release_date: 2022/11/17


optional_info:
    homepage_url: https://solr.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://solr.apache.org/guide/solr/latest/getting-started/solr-tutorial.html
    arm_recommended_minimum_version:
        version_number: 9.7.0
        release_date: 2024/09/09
        reference_content: https://solr.apache.org/news.html
        rationale: This version brings key performance improvements, including multithreaded search execution, Lucene 9.11.1 upgrade with Java 21 optimizations, and POSIX madvise support for better read-ahead on Linux. Reduced heap usage and improved async operation scaling further enhance efficiency on high-core-count systems. These improvements aren't specific to Linux/ARM64, but will definitely improve the performance on Arm based linux systems too.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://github.com/apache/solr/releases/tag/releases%2Fsolr%2F9.1.0).

---
