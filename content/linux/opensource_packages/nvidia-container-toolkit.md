---
name: NVIDIA Container Toolkit
category: Containers and Orchestration
description: NVIDIA Container Toolkit is a software suite that allows containerized applications to securely and efficiently access NVIDIA GPU resources during build and runtime.
download_url: https://github.com/NVIDIA/nvidia-container-toolkit/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.6.0
    release_date: 2021/11/18
 
 
optional_info:
    homepage_url: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/index.html
    support_caveats: NVIDIA Container Toolkit supports Linux Arm64 across major distributions. Arm64 validation includes Amazon Linux 2023 tested on an AWS g5g.2xlarge instance; Tegra-based systems are also supported. Users should validate on their target platform. Please see [this](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/supported-platforms.html).
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.18.0
        release_date: 2025/10/21
        reference_content: https://github.com/NVIDIA/nvidia-container-toolkit/releases/tag/v1.18.0
        rationale: In this release, support for building ubuntu22.04 on Arm64 was added.
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/NVIDIA/nvidia-container-toolkit/releases/tag/v1.6.0
    release_notes__recommended_minimum:
    other_info:
 
---
