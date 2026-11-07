---
name: "Firecracker"
category: Tool / Action Execution
description: "Firecracker is a virtual machine monitor for lightweight Linux microVMs on x86-64 and Arm64 hosts."
download_url: "https://github.com/firecracker-microvm/firecracker/releases"
works_on_arm: true
supported_minimum_version:
  version_number: "0.17.0"
  release_date: "2019/06/14"
optional_info:
  homepage_url: "https://firecracker-microvm.github.io/"
  support_caveats: >-
    AArch64 microVMs require compatible 4 KiB host and guest kernels. Virtualized
    hosts must expose Arm virtualization and read/write /dev/kvm access.
  alternative_options: null
  getting_started_resources:
    official_docs: null
    arm_content: "https://learn.arm.com/learning-paths/servers-and-cloud-computing/firecracker-ai-sandbox/2-prepare-the-arm-host/"
    partner_content: null
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: "https://github.com/firecracker-microvm/firecracker/releases/tag/v0.17.0"
  release_notes__recommended_minimum: null
  other_info: >-
    Firecracker v0.17.0 introduced alpha AArch64 support; it is a historical
    compatibility floor, not a deployment recommendation. The recurring hosted
    Arm64 workflow validates the v1.17.0 publisher bundle, exact Firecracker and
    jailer versions, Arm64 ELF identity, and real pre-boot API state mutation and
    rejection behavior without claiming a guest boot. The protected supplemental
    KVM workflow uses a disposable target with no privileged repository token or
    coordinator credential to require writable /dev/kvm, KVM API 12, a real Arm64
    microVM boot, guest file I/O, child exit 37, the reboot marker, and clean VMM
    shutdown. The reviewed helper uses pinned
    upstream guest-kernel and initramfs objects and verifies their measured
    hashes. Durable exact-byte guest evidence is published at
    https://github.com/ranimandepudi/ecosystem-dashboard-for-arm/releases/tag/ecosystem-arm64-validation-20261106 .
    Jailer isolation is not tested or claimed. Baseline archive SHA-256:
    e351ebe4f7a16b5873bbd51005d2e6767103cff4d5ebc829df2d3f95a93e2256.
    Publisher checksum:
    https://github.com/firecracker-microvm/firecracker/releases/download/v1.17.0/firecracker-v1.17.0-aarch64.tgz.sha256.txt .
    API schema:
    https://github.com/firecracker-microvm/firecracker/blob/v1.17.0/src/firecracker/swagger/firecracker.yaml .
    Kernel policy:
    https://github.com/firecracker-microvm/firecracker/blob/v1.17.0/docs/kernel-policy.md .
    SPDX Apache-2.0:
    https://github.com/firecracker-microvm/firecracker/blob/v1.17.0/LICENSE .
    Guest kernel SHA-256:
    8bc7fc7d1eabc0dd7dd8a33cb53b0bb11f25c09d4276757cfe16eb5c8509fa90;
    source initramfs SHA-256:
    490be704c18868cde014fbdf4e025a1548bd3efe23bff5086becdf43d6fb05ad.
---
