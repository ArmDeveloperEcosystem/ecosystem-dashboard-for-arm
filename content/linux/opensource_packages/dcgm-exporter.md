---
name: NVIDIA DCGM Exporter
category: Monitoring/Observability
description: DCGM-Exporter is a monitoring component that exposes NVIDIA GPU health, performance, and utilization metrics collected via DCGM as Prometheus-compatible HTTP endpoints, enabling observability of GPU workloads in standalone or Kubernetes cluster environments.
download_url: https://catalog.ngc.nvidia.com/orgs/nvidia/teams/k8s/containers/dcgm-exporter/tags
works_on_arm: true
supported_minimum_version:
    version_number: 2.3.2-2.6.3
    release_date: 2022/02/03
 
 
optional_info:
    homepage_url: https://docs.nvidia.com/datacenter/cloud-native/gpu-telemetry/latest/dcgm-exporter.html
    support_caveats: DCGM-Exporter runs on Linux Aarch64 and x86_64 platforms via its container images and relies on the underlying DCGM library for GPU telemetry. GPU compatibility and CUDA/driver requirements follow DCGM’s support matrix. See DCGM documentation for supported GPUs, CUDA versions, drivers, and distributions.
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/NVIDIA/dcgm-exporter#quickstart
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/NVIDIA/dcgm-exporter/releases/tag/2.3.2-2.6.3
    release_notes__recommended_minimum:
    other_info: Version 2.3.2-2.6.3 started releasing multi-arch builds, including Linux/Arm64. Please refer [this](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/k8s/containers/dcgm-exporter/tags).
 
---
