---
name: Apache Drill
category: Databases - Big-data
description: Apache Drill is an open-source SQL query engine for interactive analysis of large-scale structured and semi-structured datasets.
download_url: https://github.com/apache/drill/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.19.0
    release_date: 2021/06/15
 
 
optional_info:
    homepage_url: https://drill.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://drill.apache.org/docs/starting-drill-on-linux-and-mac-os-x/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.21.2
        release_date: 2024/06/23
        reference_content: https://issues.apache.org/jira/secure/ReleaseNote.jspa?projectId=12313820&version=12353550
        rationale: This version includes critical security and stability updates, including upgrades to Avro (1.11.3), ZooKeeper (3.5.10), and Curator (5.5.0) to address CVEs and improve dependency hygiene. Numerous memory leak fixes were implemented in join operations, batch processing, and error handling paths. Enhancements were made to better handle XML files and root attributes, with added support to disable SSL verification in the Elasticsearch plugin. Additional improvements include upgraded libraries like Jackson, POI, Bouncy Castle, and Logback, as well as fixes for UI styling, caching, and complex vector handling.
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/apache/drill/releases/tag/drill-1.19.0
    release_notes__recommended_minimum:
    other_info:
 
---
