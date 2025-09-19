---
name: Cloud Hypervisor
category: Compilers/Tools
description: Cloud Hypervisor is an open-source Virtual Machine Monitor (VMM) written in Rust, designed to execute contemporary cloud workloads with the least amount of hardware emulation possible.
download_url: https://github.com/cloud-hypervisor/cloud-hypervisor/releases
works_on_arm: true
supported_minimum_version:
  version_number: 18.0
  release_date: 2021/09/09
optional_info:
  homepage_url: https://www.cloudhypervisor.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
    official_docs: https://www.cloudhypervisor.org/docs/prologue/quick-start/
  arm_recommended_minimum_version:
    version_number: 46.0
    release_date: 2025/05/24
    reference_content: https://github.com/cloud-hypervisor/cloud-hypervisor/releases/tag/v46.0
    rationale: This release contains experimental AArch64 support for MSHV hypervisor. It is now possible to start VMs on AArch64 platforms when using MSHV hypervisor.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/cloud-hypervisor/cloud-hypervisor/releases/tag/v18.0
  release_notes__recommended_minimum: null
  other_info: Experimental support for arm64 was first added in [v0.8.0](https://github.com/cloud-hypervisor/cloud-hypervisor/releases/tag/v0.8.0). Full functionality is not included in this release. Kindly refer [here](https://github.com/cloud-hypervisor/cloud-hypervisor/blob/v0.8.0/docs/arm64.md).
---
