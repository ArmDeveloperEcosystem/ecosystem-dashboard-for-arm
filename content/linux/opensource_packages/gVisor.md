---
name: "gVisor"
category: Tool / Action Execution
description: "gVisor is a Linux application sandbox with an OCI-compatible runtime for x86-64 and Arm64 workloads."
download_url: "https://github.com/google/gvisor/releases"
works_on_arm: true
supported_minimum_version:
  version_number: "release-20210121.1"
  release_date: "2021/01/28"
optional_info:
  homepage_url: "https://gvisor.dev/"
  support_caveats: >-
    The Arm64 KVM platform requires host virtualization and access to /dev/kvm;
    the systrap platform does not. Arm64 syscall coverage differs from native
    Linux and should be checked against the official compatibility table.
  alternative_options: null
  getting_started_resources:
    official_docs: "https://gvisor.dev/docs/user_guide/compatibility/linux/arm64/"
    arm_content: "https://developer.arm.com/community/arm-community-blogs/b/servers-and-cloud-computing-blog/posts/serverless-on-arm64"
    partner_content:
      - display_name: "Linaro"
        url: "https://static.linaro.org/connect/lvc21f/presentations/LVC21F-204.pdf"
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: "https://storage.googleapis.com/gvisor/releases/release/20210121.1/aarch64/runsc.sha512"
  release_notes__recommended_minimum: null
  other_info: >-
    release-20210121.1 is the first official publisher-distributed Arm64
    release. The upstream AArch64 release pipeline landed in January 2021, and
    the canonical publisher bucket contains no earlier tagged aarch64/runsc
    object. The release-20210121.1 AArch64 executable identifies itself with
    that version and matches the publisher's SHA-512 checksum. Earlier 2019-2020
    Arm64 code, demonstrations, and preliminary documentation establish active
    development but not an earlier publisher-distributed Arm64 release. Release
    pipeline: https://github.com/google/gvisor/pull/5188 . Release-directory
    correction: https://github.com/google/gvisor/pull/5259 . Publisher artifact:
    https://storage.googleapis.com/gvisor/releases/release/20210121.1/aarch64/runsc .
    Publisher checksum:
    https://storage.googleapis.com/gvisor/releases/release/20210121.1/aarch64/runsc.sha512 .
    The modern native smoke baseline is release-20261019.0; its checksummed
    AArch64 bundle is exercised with the systrap platform and does not claim to
    reproduce the historical release environment. Baseline bundle SHA-256:
    5790f89dc94b091b5aa0f0b6596aa4391606b3fe5f069e68f440576f3388abd8.
    Publisher checksums:
    https://github.com/google/gvisor/releases/download/release-20261019.0/SHA256SUMS .
    OCI procedure: https://gvisor.dev/docs/user_guide/quick_start/oci/ .
    Platforms: https://gvisor.dev/docs/architecture_guide/platforms/ .
    SPDX Apache-2.0:
    https://github.com/google/gvisor/blob/release-20261019.0/LICENSE .
---
