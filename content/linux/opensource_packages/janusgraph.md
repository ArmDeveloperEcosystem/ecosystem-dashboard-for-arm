---
name: JanusGraph
category: Databases - Big-data
description: JanusGraph is a scalable, distributed graph database optimized for storing and querying large-scale graph data structures.
download_url: https://github.com/JanusGraph/janusgraph/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.6.3
    release_date: 2023/02/18
 
 
optional_info:
    homepage_url: https://janusgraph.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.janusgraph.org/getting-started/installation/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.1.0
        release_date: 2024/11/07
        reference_content: https://github.com/JanusGraph/janusgraph/releases/tag/v1.1.0
        rationale: In this release, vertex properties can now be inlined into composite indexes, significantly improving fetch performance. Key compatibility includes Cassandra 3.11.10/4.0.6, HBase 2.6.0, ScyllaDB 6.2.0, Elasticsearch 6–8.15.3, and TinkerPop 3.7.3. Pre-packaged setup includes Cassandra 4.0.6 and Elasticsearch 7.17.8.
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Version "0.6.3" has been successfully installed and tested on the Neoverse N1, prior versions are failing to run.
 
---
