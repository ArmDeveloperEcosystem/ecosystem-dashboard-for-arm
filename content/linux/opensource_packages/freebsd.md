---
name: FreeBSD
category: Operating System
description: FreeBSD is an operating system used to power modern servers, desktops, and embedded platforms.
download_url: https://www.freebsd.org/where/
works_on_arm: true
supported_minimum_version:
  version_number: 11.0
  release_date: 2016/10/10
optional_info:
  homepage_url: https://www.freebsd.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://www.freebsd.org/releases/11.0R/installation/
    arm_content:
    partner_content:
  arm_recommended_minimum_version:
    version_number: 14.0
    release_date: 2023/11/20
    reference_content: https://www.freebsd.org/releases/14.0R/relnotes/
    rationale: This version enhances Arm64 (AArch64) support with COMPAT_LIB32, enabling 32-bit Armv7 binaries to run natively on Arm64 systems. The SMP system now supports up to 1024 cores on amd64 and arm64. Many kernel CPU sets are now dynamically allocated to avoid consuming excessive memory. Kinst (DTrace) has been ported to Arm64, enabling fine-grained kernel instruction tracing. Cloud readiness has advanced with official Arm64 images for Azure. Both UFS and experimental ZFS images are available. Gen2 VMs are now supported. LLVM’s AddressSanitizer can now be used in arm64 kernels as well as amd64.
optional_hidden_info:
  release_notes__supported_minimum: https://www.freebsd.org/releases/11.0R/announce/
  release_notes__recommended_minimum: null
  other_info: null
---
