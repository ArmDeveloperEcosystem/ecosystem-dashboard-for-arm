---
name: Ampere Optimized ONNX Runtime
category: AI/ML
description: Ampere Optimized ONNX Runtime is an inference acceleration backend for ONNX Runtime that enhances deep learning performance on Ampere Altra ARM CPUs using model optimizations, vectorized compute kernels, and multi-threaded execution without requiring model changes.
download_url: https://hub.docker.com/r/amperecomputingai/onnxruntime/tags
works_on_arm: true
supported_minimum_version:
    version_number: 1.4.0
    release_date: 2022/12/02
 
 
optional_info:
    homepage_url: https://amperecomputing.com/developers/power-your-ai
    support_caveats: Ampere Optimized ONNX Runtime targets the Ampere Altra family of Arm64 processors. While Arm64 compatibility may predate 1.4.0, official packaged distributions (Docker images) are available starting from version 1.4.0.
    alternative_options:
    getting_started_resources:
        official_docs: https://amperecomputing.com/assets/Ampere_Optimized_ONNXRuntime_Documentation_v1_8_0_9646259707.pdf
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
    other_info: The release notes for the initial Linux/Arm64 support isn't available. Docker images for Aarch64 are available from version 1.4.0 onwards, which officially justifies the Arm support.
 
---
