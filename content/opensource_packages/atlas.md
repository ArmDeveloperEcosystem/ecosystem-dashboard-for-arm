---
name: Apache Atlas
category: Databases - Big-data
description: Apache Atlas is an open-source framework for metadata management and data governance, created to support organizations in effectively overseeing and managing their data assets.
download_url: https://atlas.apache.org/#/Downloads
works_on_arm: true
supported_minimum_version:
    version_number: 2.3.0
    release_date: 2022/12/07


optional_info:
    homepage_url: https://atlas.apache.org/#/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://atlas.apache.org/#/BuildInstallation
    arm_recommended_minimum_version:
        version_number: 2.4.0
        release_date: 2025/01/02
        reference_content: https://atlas.apache.org/#/WhatsNew-2.4
        rationale: This version introduces key features such as downloadable search results, CouchBase hook integration, audit aging, and enhanced hook notification analysis. It adds generic ignore patterns across all hooks and introduces liveness/readiness probes. Significant performance enhancements are made in export/import, relationship handling, and lineage processing. The release improves message processing in hook consumers and adds SNAPPY compression support for HBase. Chinese character support is added to search, and major dependency upgrades are applied across the stack. UI enhancements span glossary, entity views, and text editing, and logging is now handled via Logback instead of Log4j. Docker image support has also been improved.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum: 
    other_info: Linux/ARM64 release notes are not available. Installation and Testing were done using released tar files.

---
