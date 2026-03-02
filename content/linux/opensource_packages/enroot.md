---
name: NVIDIA Enroot
category: Containers and Orchestration
description: ENROOT is a lightweight container runtime that converts standard container or OS images into unprivileged, user-space sandboxes, enabling portable and reproducible execution with minimal isolation overhead, well-suited for HPC and GPU-enabled environments where performance matters more than strong container isolation.
download_url: https://github.com/NVIDIA/enroot/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.1.0
    release_date: 2019/10/17
 
 
optional_info:
    homepage_url: https://github.com/NVIDIA/enroot
    support_caveats: Enroot provides Linux Aarch64 artifacts starting with v2.1.0. GPU support is optional and, when enabled, requires NVIDIA GPUs (Fermi / compute capability ≥ 2.1 or newer), NVIDIA driver ≥ 361.93, and libnvidia-container-tools ≥ 1.0. GPU compatibility follows the installed NVIDIA driver and CUDA stack. Please refer [this](https://github.com/NVIDIA/enroot/blob/main/doc/requirements.md#gpu-support-optional).
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/NVIDIA/enroot#documentation
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
    other_info: The release notes for the initial Linux/Arm64 support isn't available. Arm64 artifacts are available from version 2.1.0 onwards. Please refer [this](https://github.com/NVIDIA/enroot/releases/tag/v2.1.0).
 
---
