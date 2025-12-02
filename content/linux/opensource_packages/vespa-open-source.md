---
name: Vespa (open source)
category: AI/ML
description: Vespa is a search and data processing engine designed for real-time AI data processing applications.
download_url: https://hub.docker.com/r/vespaengine/vespa/
works_on_arm: true
supported_minimum_version:
    version_number: 8.37.26
    release_date: 2022/08/18


optional_info:
    homepage_url: https://vespa.ai/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.vespa.ai/en/getting-started.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 8.344
        release_date: 2024/05/31
        reference_content: https://blog.vespa.ai/vespa-newsletter-may-2024/
        rationale: Vespa 8.344 introduces optimized value type conversions and distance computations for vector search operations. These enhancements yield up to 2× QPS improvement for float vectors with Euclidean distance and up to 9× QPS for int8 vectors with Euclidean distance. Bit vectors show up to a 40% increase in QPS for exact nearest neighbor queries, while bfloat16 vectors with HNSW indexing see up to 50% faster feed throughput and 40% higher QPS. Int8 vectors also benefit with up to 5× QPS gain for dotproduct and 30% for angular distance queries. While these benchmarks are measured on x86-64, similar (though smaller) gains are expected on Arm64 systems.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Docker minimum version vrom 8.37.26 in this blog - blog.vespa.ai/preview-of-vespa-on-arm64/. Commercial version as well.

---
