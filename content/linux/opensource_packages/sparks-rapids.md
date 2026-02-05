---
name: NVIDIA Spark-Rapids
category: AI/ML
description: RAPIDS Accelerator for Apache Spark is a GPU-accelerated plugin for Apache Spark that uses RAPIDS libraries (such as cuDF) to speed up large-scale data processing, analytics, and AI/ML workloads by offloading SQL and DataFrame operations from CPUs to GPUs, including accelerated shuffle with GPU-to-GPU communication.
download_url: https://nvidia.github.io/spark-rapids/docs/download.html
works_on_arm: true
supported_minimum_version:
    version_number: 24.02.0
    release_date: 2024/03/12
 
 
optional_info:
    homepage_url: https://nvidia.github.io/spark-rapids/
    support_caveats: Spark-Rapids v24.02.0 includes official Arm64 builds and is tested on V100, T4, A10/A100, L4, and H100 GPUs with CUDA 11.8–12.0. Hardware requirements may differ in later releases. Users should consult the version-specific documentation. Please refer [this](https://nvidia.github.io/spark-rapids/docs/download.html).
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.nvidia.com/spark-rapids/user-guide/latest/getting-started/overview.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/NVIDIA/spark-rapids/blob/main/docs/archives/CHANGELOG_24.02-to-24.12.md#release-2402
    release_notes__recommended_minimum:
    other_info:
 
---
