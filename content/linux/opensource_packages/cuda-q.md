---
name: CUDA-Q
category: HPC
description: CUDA-Q is a hybrid quantum–classical computing platform that provides C++ and Python tools to program and integrate quantum processors with CPUs and GPUs in a unified runtime.
download_url: https://github.com/NVIDIA/cuda-quantum/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.4.1
    release_date: 2023/10/04
 
 
optional_info:
    homepage_url: https://nvidia.github.io/cuda-quantum/latest/index.html
    support_caveats: CUDA-Q supports Linux Arm64 (ARM v8-A+) hosts for CPU-only and GPU-accelerated workloads, with GPU simulation supported on NVIDIA Turing, Ampere, Ada, Hopper, and Blackwell architectures subject to CUDA and driver requirements. Please refer [this](https://nvidia.github.io/cuda-quantum/latest/using/install/local_installation.html#dependencies-and-compatibility).
    alternative_options:
    getting_started_resources:
        official_docs: https://nvidia.github.io/cuda-quantum/latest/using/quick_start.html#install-cuda-q
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 0.8.0
        release_date: 2024/08/05
        reference_content: https://github.com/NVIDIA/cuda-quantum/releases/tag/0.8.0
        rationale: In this release, LLVM relocation overflow for Aarch64 was fixed.
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/NVIDIA/cuda-quantum/releases/tag/0.4.1
    release_notes__recommended_minimum:
    other_info:
 
---

