---
name: NVSentinel
category: Monitoring/Observability
description: NVSentinel is a Kubernetes-based GPU node resilience system that automatically detects, classifies, and remediates hardware and software faults in GPU-enabled clusters to maintain high availability and reliability.
download_url: https://github.com/NVIDIA/NVSentinel/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.3.0
    release_date: 2025/11/07
 
 
optional_info:
    homepage_url: https://github.com/NVIDIA/NVSentinel
    support_caveats: NVSentinel provides multi-architecture container images (linux/amd64, linux/arm64) starting with v0.3.0. While Arm64 container support is officially enabled, NVIDIA does not publish a dedicated Arm64 GPU hardware compatibility matrix for NVSentinel. Users should validate on their target Arm64 platform.
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/NVIDIA/NVSentinel#-quick-start
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/NVIDIA/NVSentinel/releases/tag/v0.3.0
    release_notes__recommended_minimum:
    other_info:
 
---
