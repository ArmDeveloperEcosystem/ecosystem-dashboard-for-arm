---
name: NVIDIA BioNeMo-Framework
category: AI/ML
description: BioNeMo is an NVIDIA software ecosystem for building, training, fine-tuning, and deploying AI models for life sciences, providing optimized biomolecular models, workflows, and production-ready inference microservices for biological and therapeutic applications.
download_url: https://catalog.ngc.nvidia.com/orgs/nvidia/teams/clara/containers/bionemo-framework
works_on_arm: true
supported_minimum_version:
    version_number: 2.2
    release_date: 2024/12/19
 
 
optional_info:
    homepage_url: https://nvidia.github.io/bionemo-framework/
    support_caveats: BioNeMo Framework v2.2+ provides Arm64 container images (e.g., for GH200 platform). Documentation for BioNeMo lists supported GPUs with Compute Capability ≥8.0 (H100, L4, L40, A100, A40, A30, A10, A16, A2, RTX 6000/A6000/A5000/A4000) on supported hosts. Arm64 GPU validation details are not separately published. Users should confirm compatibility with their CUDA driver and GPU architecture. Please refer [this](https://nvidia.github.io/bionemo-framework/main/getting-started/pre-reqs/).
    alternative_options:
    getting_started_resources:
        official_docs: https://nvidia.github.io/bionemo-framework/main/getting-started/pre-reqs/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.6
        release_date: 2025/04/30
        reference_content: https://github.com/NVIDIA/bionemo-framework/releases/tag/v2.6
        rationale: In this release, docker build was fixed for Arm and Arm compatible containers were released.
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/NVIDIA/bionemo-framework/releases/tag/v2.2
    release_notes__recommended_minimum:
    other_info:
 
---
