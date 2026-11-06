---
name: "Microsandbox"
category: Containers and Orchestration
description: "Microsandbox is a local microVM runtime and library for isolated application workloads."
download_url: "https://github.com/superradcompany/microsandbox/releases"
works_on_arm: true
supported_minimum_version:
  version_number: "0.1.0"
  release_date: "2025/05/20"
optional_info:
  homepage_url: "https://github.com/superradcompany/microsandbox"
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: null
    arm_content: "https://learn.arm.com/install-guides/microsandbox/"
    partner_content: null
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: "https://github.com/superradcompany/microsandbox/releases/tag/microsandbox-v0.1.0"
  release_notes__recommended_minimum: null
  support_context: >-
    Version 0.1.0 is the first Microsandbox-branded release with Linux AArch64
    binaries. The predecessor Monocore shipped AArch64 assets in December 2024,
    but is not a Microsandbox-branded release.
  other_info: >-
    The runtime requires hardware virtualization, usable /dev/kvm access, and
    firmware matching the selected release. The recurring hosted Arm64 smoke
    baseline is v0.7.11. It verifies the checksummed Linux AArch64 bundle,
    executable and firmware ABI identity, exact CLI version, launch-protocol and
    schema contracts, and a local volume create/list/remove lifecycle. That lane
    does not claim a guest boot. A separate protected-main supplemental KVM lane
    executes the same release with its matching libkrun firmware and a
    digest-pinned Alpine Arm64 guest, requiring a real guest boot, Arm64
    architecture observation, guest I/O, exit propagation, lifecycle behavior,
    and cleanup. Durable real-guest evidence from 2026/11/06 is retained at
    https://github.com/ranimandepudi/ecosystem-dashboard-for-arm/releases/tag/ecosystem-arm64-validation-20261106.
    SPDX Apache-2.0:
    https://github.com/superradcompany/microsandbox/blob/v0.7.11/LICENSE .
    Baseline source commit df3e0f7dd69280b88f6e28d6d3cf5fe4bb4a87a0;
    Linux AArch64 bundle SHA-256:
    ab1c371e85ff101581b7cf092dbaad6f5b720736ca042aa0d6d4b950f57d6709.
    The bundle includes matching libkrunfw.so.5.6.1. Do not substitute a
    different firmware or installer release.
---
