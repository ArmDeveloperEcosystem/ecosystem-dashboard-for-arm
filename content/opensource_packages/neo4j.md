---
name: Neo4j
category: Databases - noSQL
description: Neo4j is a state-of-the-art graph database designed to handle data with complex interconnections unlike conventional databases it utilizes a graph-based approach where data is represented as nodes entities and edges connections.
download_url: https://github.com/neo4j/neo4j/tags
works_on_arm: true
supported_minimum_version:
    version_number: v5.2.0
    release_date: 2022/11/21


optional_info:
    homepage_url: http://neo4j.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://neo4j.com/docs/operations-manual/current/installation/linux/
    arm_recommended_minimum_version:
        version_number: 5.5
        release_date: 2023/09/27
        reference_content: https://aws.amazon.com/blogs/apn/give-your-graph-workload-a-cost-performance-boost-with-neo4j-and-aws-graviton/
        rationale: This version of Neo4j shows significant performance boost of 13-146% and Overall cost-performance boost of 32-189% on AWS Graviton 3 processors.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Neo4j was installed using the command "apt install neo4j".

---
