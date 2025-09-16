---
name: OpenEuler
category: Operating System
description: OpenEuler is an open source project incubated and operated by the OpenAtom Foundation.
download_url: https://www.openeuler.org/en/download/archive/
works_on_arm: true
supported_minimum_version:
  version_number: 20.03 LTS
  release_date: 2020/03/01
optional_info:
  homepage_url: https://www.openeuler.org/en/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Microsoft Azure
        url: https://apps.microsoft.com/detail/9nwb78l1mps2?hl=en-mt&gl=MT
    official_docs: https://docs.openeuler.org/en/
  arm_recommended_minimum_version:
    version_number: 24.03 LTS SP2
    release_date: 2024/03/01
    reference_content: https://docs.openeuler.org/en/docs/24.03_LTS_SP2/server/releasenotes/releasenotes/key_features.html
    rationale: OpenEuler 24.03 LTS SP2 delivers key optimizations for Arm and Aarch64 platforms. The toolchain is upgraded to GCC 12.3 with support for Armv9-A, SVE, AutoFDO, and structure layout optimization, improving performance on Aarch64 workloads like MySQL and SPEC CPU. The kernel adds folio-based memory management with contiguous bit support, multi-size transparent hugepages (mTHP), and ext4 large folio I/O optimizations to reduce TLB misses and boost efficiency on Arm64. Aarch64 syscall and interrupt paths are accelerated via xcall and xint, while VM performance benefits from improved halt polling. For confidential computing, openEuler introduces virtCCA, a virtualization framework based on Arm CCA and Secure EL2, enabling secure confidential VMs with device passthrough and crypto acceleration. On the embedded side, openEuler expands Aarch64 SoC support (Raspberry Pi, Rockchip, Phytium, Kunpeng, HiSilicon, etc.) and integrates UniProton RTOS for mixed-criticality deployments across Cortex-A and Cortex-M cores.
optional_hidden_info:
  release_notes__supported_minimum: https://docs.openeuler.org/en/docs/20.03_LTS/docs/Releasenotes/installing-the-os.html
  release_notes__recommended_minimum: null
  other_info: Tested this package by creating docker containers for the docker image "openeuler/openeuler". [DockerHub source](https://hub.docker.com/r/openeuler/openeuler).
---
