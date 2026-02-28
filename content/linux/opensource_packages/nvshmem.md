---
name: NVSHMEM
category: HPC
description: NVSHMEM is a GPU communication library that implements the OpenSHMEM PGAS (Partitioned Global Address Space) programming model for clusters of NVIDIA GPUs, enabling low-latency, one-sided communication (get/put/atomics) across GPUs connected via NVLink, PCIe, and InfiniBand.
download_url: https://developer.nvidia.com/nvshmem-downloads?target_os=Linux&target_arch=arm64-sbsa
works_on_arm: true
supported_minimum_version:
    version_number: 2.10.1
    release_date: 2024/01/01
 
 
optional_info:
    homepage_url: https://docs.nvidia.com/nvshmem/api/index.html
    support_caveats: NVSHMEM supports NVIDIA Grace (Arm64) processors and has been tested on Grace systems with NVIDIA Ampere (A100), Hopper (H100), and Blackwell GPUs across supported CUDA releases. GPU and CUDA compatibility follow the tested NVSHMEM version; users should validate on their target platform. Please refer [this](https://docs.nvidia.com/nvshmem/release-notes-install-guide/release-notes/release-3519.html).
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.nvidia.com/nvshmem/release-notes-install-guide/install-guide/abstract.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://docs.nvidia.com/nvshmem/release-notes-install-guide/prior-releases/release-2101.html
    release_notes__recommended_minimum:
    other_info: NVSHMEM 2.10.1 includes testing on NVIDIA Grace processors (Arm64). An explicit standalone release date for NVSHMEM 2.10.1 is not published. However, NVIDIA HPC SDK 23.9 release notes list NVSHMEM version 2.10.1, indicating that the release occurred on or before the HPC SDK 23.9 timeframe (late 2023 / early 2024). Please refer [this](https://docs.nvidia.com/hpc-sdk/archive/23.9/pdf/hpc-sdk239rn.pdf).
 
---
