---
name: CuTile Python
category: Languages and Frameworks
description: CuTile Python is a CUDA-based Python DSL that enables writing high-performance, tile-oriented GPU kernels while automatically leveraging advanced NVIDIA GPU hardware features.
download_url: https://pypi.org/project/cuda-tile/#history
works_on_arm: true
supported_minimum_version:
    version_number: 1.0.0
    release_date: 2025/12/05
 
 
optional_info:
    homepage_url: https://docs.nvidia.com/cuda/cutile-python/
    support_caveats: CuTile Python supports Linux Aarch64 with official manylinux Aarch64 wheels. GPU execution requires CUDA Toolkit 13.1+, NVIDIA driver R580 or later, and an NVIDIA GPU with compute capability in the 10.x or 12.x series. Users should validate on their target Arm64 platform. Please refer [this](https://docs.nvidia.com/cuda/cutile-python/quickstart.html#prerequisites).
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.nvidia.com/cuda/cutile-python/quickstart.html#installing-cutile-python
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
    other_info: The release notes for the initial Linux/Arm64 support isn't available. However, Pypi releases manylinux Aarch64 wheels from version 1.0.0 onwards. Please see [this](https://pypi.org/project/cuda-tile/1.0.0/#files).
 
---
