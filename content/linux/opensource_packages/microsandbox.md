---
name: Microsandbox
category: Containers and Orchestration
description: Microsandbox is a local microVM runtime and library for isolated application workloads.
download_url: https://github.com/superradcompany/microsandbox/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.1.0
    release_date: 2025/05/20

optional_info:
    homepage_url: https://github.com/superradcompany/microsandbox
    support_caveats_inline: true
    support_caveats: "Linux Arm64 requires glibc 2.28+, hardware virtualization with read/write /dev/kvm access, and the matching bundled firmware. When running inside a VM, nested virtualization must be available."
    getting_started_resources:
        official_docs: https://github.com/superradcompany/microsandbox/blob/v0.7.11/docs/troubleshooting/linux.mdx
        arm_content: https://learn.arm.com/install-guides/microsandbox/

optional_hidden_info:
    support_context: "The 0.1.0 minimum is the first Microsandbox-branded release with Linux AArch64 binaries; predecessor Monocore already shipped AArch64 assets in December 2024. Docker access alone is insufficient to provide the required KVM access."
    release_notes__supported_minimum: https://github.com/superradcompany/microsandbox/releases/tag/microsandbox-v0.1.0
    other_info: "SPDX: Apache-2.0, verified in https://github.com/superradcompany/microsandbox/blob/v0.7.11/LICENSE. Canonical repository superradcompany/microsandbox; microsandbox/microsandbox and appcypher/monocore redirect here. Predecessor evidence: https://github.com/superradcompany/microsandbox/releases/tag/monocore-v0.1.0 (2024-12-03), not the first Microsandbox-branded version. No Arm performance-based recommended minimum established. Smoke baseline v0.7.11 (2026-10-24), immutable GitHub release, source commit df3e0f7dd69280b88f6e28d6d3cf5fe4bb4a87a0; Linux AArch64 bundle SHA-256 ab1c371e85ff101581b7cf092dbaad6f5b720736ca042aa0d6d4b950f57d6709 matches upstream checksums.sha256. Bundle includes msb and matching libkrunfw.so.5.6.1; do not substitute latest firmware or latest installer. Guest image pinned to the Linux Arm64 manifest of official Alpine 3.22.2. No newer-version or cloud-backend validation is asserted. Implementation status: the package workflow mandates guest execution and fails without usable KVM. The checked ubuntu-24.04-arm hosted runner lacks /dev/kvm; no native guest success is claimed. Keep integration draft until a reviewed KVM execution path preserves the batch topology guard. Version/help/doctor or API-only checks cannot establish guest execution."
---
