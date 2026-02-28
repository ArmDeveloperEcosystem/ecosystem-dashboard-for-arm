---
name: NVIDIA DALI
category: AI/ML
description: NVIDIA DALI is a GPU-accelerated data loading and preprocessing library that offloads image, video, and audio pipelines from CPU to GPU to remove input bottlenecks and improve deep learning training and inference throughput.
download_url: https://github.com/NVIDIA/DALI/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.11.0
    release_date: 2019/06/27
 
 
optional_info:
    homepage_url: https://docs.nvidia.com/deeplearning/dali/user-guide/docs/index.html
    support_caveats: NVIDIA DALI supports linux Aarch64 (SBSA) with prebuilt manylinux Aarch64 wheels available from v0.25.0 onward. GPU support on Arm64 includes NVIDIA Volta, Turing, Ampere, Hopper, and Blackwell architectures (SM 7.0+ for CUDA 12, SM 7.5+ for CUDA 13), with driver requirements r525+ (CUDA 12) and r580+ (CUDA 13). Refer to the [DALI support matrix](https://docs.nvidia.com/deeplearning/dali/user-guide/docs/support_matrix.html) for full compatibility details.
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.nvidia.com/deeplearning/dali/user-guide/docs/installation.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.38.0
        release_date: 2024/05/15
        reference_content: https://github.com/NVIDIA/DALI/releases/tag/v1.38.0
        rationale: In this release, CMake to Aarch64 base docker image was added.
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/NVIDIA/DALI/releases/tag/v0.11.0
    release_notes__recommended_minimum:
    other_info:
 
---
