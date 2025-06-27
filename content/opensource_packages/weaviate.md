---
name: Weaviate
category: Database
description: Weaviate is a robust, fast, and scalable open-source database that stores data as vectors in the cloud. It leverages advanced machine learning to convert diverse data types into a searchable vector database.
download_url: https://github.com/weaviate/weaviate/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.18.0
    release_date: 2023/03/07


optional_info:
    homepage_url: https://weaviate.io/developers/weaviate/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://weaviate.io/developers/weaviate/installation
    arm_recommended_minimum_version:
        version_number: 1.21.0
        release_date: 2023/08/22
        reference_content: https://weaviate.io/blog/weaviate-1-21-release#multiprocessing-speedups-for-arm64-processors
        rationale: This version uses simd multiprocessing instructions for faster distance calculations on ARM64 processors, which results in significant performance (up to 40%) improvements, especially for large data sets and high-dimensional embeddings.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/weaviate/weaviate/releases/tag/v1.18.0
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. The first Linux/ARM64 tar is available in version v1.18.0.

---
