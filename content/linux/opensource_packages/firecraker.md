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
    compatibility floor, not a deployment recommendation. The modern smoke
    baseline is v1.17.0 and requires a real KVM guest boot. A pre-boot API check
    alone does not establish compatibility. The reviewed helper uses pinned
    upstream guest-kernel and initramfs objects, verifies their measured hashes,
    checks guest AArch64 identity and I/O, and requires guest exit propagation.
    GitHub-hosted ubuntu-24.04-arm currently exposes no /dev/kvm, so the native
    workflow must remain draft until an approved Arm64 KVM runner executes the
    exact proposed bytes. Baseline archive SHA-256:
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
