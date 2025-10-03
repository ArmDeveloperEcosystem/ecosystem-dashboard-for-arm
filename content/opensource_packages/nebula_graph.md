---
name: Nebula Graph
category: Databases - Big-data
description: NebulaGraph is open source graph database that allow users to access, use and contribute to the codebase freely. 
download_url: https://github.com/vesoft-inc/nebula/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.2.0
    release_date: 2020/12/08


optional_info:
    homepage_url: https://www.nebula-graph.io/
    support_caveats:
    alternative_options: 
    getting_started_resources:
        official_docs: https://docs.nebula-graph.io/master/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.5.0
        release_date: 2023/07/26
        reference_content: https://www.nebula-graph.io/posts/nebulagraph-benchmark-3.5.0
        rationale: NebulaGraph v3.5.0 introduced substantial performance enhancements, particularly for the FIND ALL PATH queries, which experienced improvements ranging from approximately 50% to 500% across varying depths, with some scenarios observing up to a 600% increase in performance for 1 to 5 hops. Additionally, the Match2HOP_count operation saw a performance boost of around 15%. While these optimizations are general and not explicitly targeted at Arm architectures, they are likely to benefit performance across all platforms, including Arm-based systems.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/vesoft-inc/nebula/releases/tag/v1.2.0
    release_notes__recommended_minimum:
    other_info: 

---
