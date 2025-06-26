---
name: Lucene
category: Databases - noSQL
description: Apache Lucene is an open-source search engine library, part of the Apache Software Foundation. It is released under the Apache License 2.0, which allows developers to use, modify, and distribute the software freely.
download_url: https://github.com/apache/lucene/releases
works_on_arm: true
supported_minimum_version:
    version_number: 9.9.0
    release_date: 2023/12/04


optional_info:
    homepage_url: https://lucene.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/apache/lucene#building
    arm_recommended_minimum_version:
        version_number: 10.2.0
        release_date: 2025/04/10
        reference_content: https://github.com/apache/lucene/releases/tag/releases%2Flucene%2F10.2.0
        rationale: This version delivers major search-time performance gains through enhanced BKD tree encoding, vectorized query processing, and bit set–based postings list storage. Key optimizations include merging dense clause matches via bitwise ANDs and the integration of the ACORN-1 algorithm for vector search. Benchmark tests show query speedups ranging from 38% to 5×, particularly for term and range queries. Indexing behavior was tuned by increasing the default segment floor size to improve query efficiency. New features include TopDocs RRF fusion and SeededKnnVectorQuery for better vector entry points. Additional enhancements bring support for Java 24’s vector API, Unicode improvements in RegexpQuery, and 25% faster HNSW graph indexing.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://github.com/apache/lucene/releases/tag/releases%2Flucene%2F9.9.0).

---

