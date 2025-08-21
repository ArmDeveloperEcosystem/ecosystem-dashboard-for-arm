---
name: Milvus
category: Data-format
description: Milvus is a high-performance, open-source vector database for efficient similarity searches and machine-learning tasks. It excels at managing large-scale vector data, allowing for rapid retrieval and analysis, making it perfect for AI-driven applications such as recommendation engines and image recognition.
download_url: https://pypi.org/project/pymilvus/#history
works_on_arm: true
supported_minimum_version:
    version_number: 2.3.0
    release_date: 2023/08/23


optional_info:
    homepage_url: https://milvus.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://milvus.io/docs/quickstart.md#Install-Milvus
    arm_recommended_minimum_version:
        version_number: 2.3.12
        release_date: 2024/03/15
        reference_content: https://github.com/milvus-io/milvus/releases/tag/v2.3.12
        rationale: In this version, jemalloc, a high-performance memory allocator, has been optimized to better support 64KB memory pages on AArch64 (ARM64) systems. This results in faster allocations, better cache performance, and less waste on servers using 64KB pages.

optional_hidden_info:
    release_notes__supported_minimum: https://milvus.io/docs/v2.3.x/release_notes.md#v230
    release_notes__recommended_minimum:
    other_info:

---
