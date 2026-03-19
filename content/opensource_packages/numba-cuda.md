---
name: Numba CUDA
category: Languages and Frameworks
description: Numba CUDA is a CUDA-based Python JIT compilation framework that allows developers to write and run SIMT-style GPU kernels and device functions directly in Python, enabling custom GPU acceleration and integration with CUDA libraries.
download_url: https://github.com/NVIDIA/numba-cuda/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.0.0
    release_date: 2024/06/25
 
 
optional_info:
    homepage_url: https://nvidia.github.io/numba-cuda/
    support_caveats: Numba-CUDA provides official manylinux Aarch64 wheels from v0.21.1 onward. GPU support follows the CUDA Toolkit in use. For CUDA 12, supported GPUs span Compute Capability 5.0–12.1; for CUDA 13, Compute Capability 7.5–12.1. Numba-CUDA currently supports CUDA Toolkit versions 12 and 13. Users should validate on their target Arm64 platform. Please see [this](https://nvidia.github.io/numba-cuda/user/installation.html#requirements).
    alternative_options:
    getting_started_resources:
        official_docs: https://nvidia.github.io/numba-cuda/user/installation.html
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
    other_info: The release notes for the initial Linux/Arm64 support isn't available. However, the first release on Pypi, 0.0.0, can be installed via pip and python version 3.7. Kindly note that the manylinux Aarch64 wheels are available from version 0.21.1 onwards. Please see [this](https://pypi.org/project/numba-cuda/0.21.1/#files).
 
---
