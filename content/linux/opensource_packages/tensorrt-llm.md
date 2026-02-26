---
name: TensorRT-LLM
category: AI/ML
description: TensorRT-LLM is an open-source NVIDIA library that accelerates and optimizes large language model inference on GPUs, providing high-performance runtimes, advanced parallelism, and production-ready optimization features.
download_url: https://github.com/NVIDIA/TensorRT-LLM/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.20.0
    release_date: 2025/06/19
 
 
optional_info:
    homepage_url: https://nvidia.github.io/TensorRT-LLM/index.html
    support_caveats: Linux Aarch64 is a supported host architecture for TensorRT-LLM across NVIDIA Ampere, Ada, Hopper, Grace Hopper, and Blackwell GPUs. Users should validate on their target platform. Please refer [this](https://nvidia.github.io/TensorRT-LLM/reference/support-matrix.html#hardware).
    alternative_options:
    getting_started_resources:
        official_docs: https://nvidia.github.io/TensorRT-LLM/installation/index.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: The release notes for the initial Linux/Arm64 support isn't available. However, TensorRT-LLM container images for Arm64 are available from version 0.20.0 onwards. Please see [this](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/tensorrt-llm/containers/release/tags).
 
---
