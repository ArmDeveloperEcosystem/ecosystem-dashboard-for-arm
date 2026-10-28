---
name: Firecracker
category: Tool / Action Execution
description: Firecracker is an Apache-2.0 virtual machine monitor for lightweight Linux microVMs on x86_64 and aarch64.
download_url: https://github.com/firecracker-microvm/firecracker/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.17.0
    release_date: 2019/06/14

optional_info:
    homepage_url: https://firecracker-microvm.github.io/
    support_caveats: >-
        Requires an Arm64 Linux host with read/write access to /dev/kvm and
        compatible host and guest kernels. Virtual machines must expose
        hardware virtualization.
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/firecracker-ai-sandbox/2-prepare-the-arm-host/
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/firecracker-microvm/firecracker/releases/tag/v0.17.0
    release_notes__recommended_minimum:
    other_info: >-
        Version v0.17.0 (2019/06/14) introduced alpha aarch64 support, not
        production-ready support. Upstream validated kernel combinations use
        4 KiB pages. An aarch64 CPU alone is insufficient: virtualized hosts
        must expose KVM to the process. Running the pre-boot API does not
        demonstrate guest execution. Production deployments should use the
        matching jailer and follow upstream host, guest-kernel, and isolation
        guidance.
        Historical alpha introduction:
        https://github.com/firecracker-microvm/firecracker/releases/tag/v0.17.0
        Modern smoke baseline: v1.17.0, published 2026/09/10,
        firecracker-v1.17.0-aarch64.tgz,
        SHA256 e351ebe4f7a16b5873bbd51005d2e6767103cff4d5ebc829df2d3f95a93e2256.
        Publisher checksum:
        https://github.com/firecracker-microvm/firecracker/releases/download/v1.17.0/firecracker-v1.17.0-aarch64.tgz.sha256.txt
        API schema:
        https://github.com/firecracker-microvm/firecracker/blob/v1.17.0/src/firecracker/swagger/firecracker.yaml
        Kernel requirements:
        https://github.com/firecracker-microvm/firecracker/blob/v1.17.0/docs/kernel-policy.md
        License: https://github.com/firecracker-microvm/firecracker/blob/v1.17.0/LICENSE
        Guest kernel and source rootfs are exact upstream CI objects under
        https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/20261021-1e5fcc27b59f-0/aarch64/
        vmlinux-6.1.188 SHA256:
        8bc7fc7d1eabc0dd7dd8a33cb53b0bb11f25c09d4276757cfe16eb5c8509fa90;
        initramfs.cpio SHA256:
        490be704c18868cde014fbdf4e025a1548bd3efe23bff5086becdf43d6fb05ad.
        These two hashes were measured from the upstream objects on 2026/10/27,
        not taken from a publisher signature. The probe replaces /init in the
        verified BusyBox initramfs and logs the derived initramfs digest.

---
