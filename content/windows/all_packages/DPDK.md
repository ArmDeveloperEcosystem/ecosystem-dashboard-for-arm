---
name: DPDK
category: Networking
description: DPDK is a set of libraries and drivers for fast packet processing.
download_url: https://core.dpdk.org/download/
works_on_arm: true
supported_minimum_version:
  version_number: 20.11
  release_date: 2020/12/10

optional_info:
  homepage_url: https://www.dpdk.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://doc.dpdk.org/guides/windows_gsg/index.html
    arm_content:
    partner_content:
  arm_recommended_minimum_version:
    version_number: 23.03
    release_date: 2023/03/31
    reference_content: https://doc.dpdk.org/guides/rel_notes/release_23_03.html
    rationale: This version adds power monitor and wake up API support with WFE/SVE instructions for the Arm architecture.
optional_hidden_info:
  release_notes__supported_minimum: https://doc.dpdk.org/guides/rel_notes/release_2_2.html
  release_notes__recommended_minimum: null
  other_info: Project uses Github-actions CI and for aarch64, it is built through cross-compilation.
---
