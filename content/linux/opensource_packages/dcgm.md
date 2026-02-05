---
name: NVIDIA DCGM
category: Monitoring/Observability
description: NVIDIA Data Center GPU Manager (DCGM) is a GPU management and monitoring suite for NVIDIA data center GPUs that provides health monitoring, diagnostics, telemetry, policy-based governance, and Kubernetes integration (via DCGM Exporter) to improve reliability and operational efficiency in clustered environments.
download_url: https://github.com/NVIDIA/DCGM/tags
works_on_arm: true
supported_minimum_version:
    version_number: 2.0.13
    release_date: 2020/10/31
 
 
optional_info:
    homepage_url: https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/index.html
    support_caveats: DCGM supports Linux Aarch64 on supported distributions with NVIDIA GPUs (Kepler/K80 and newer), requiring CUDA 7.5+ and an NVIDIA driver version R450+. NVSwitch systems (e.g., DGX/HGX A100+) require Fabric Manager installed separately. Please refer [this](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/getting-started.html#supported-platforms).
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/getting-started.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://docs.nvidia.com/datacenter/dcgm/2.0/dcgm-release-notes/index.html#unique_905593957
    release_notes__recommended_minimum:
    other_info:
 
---
