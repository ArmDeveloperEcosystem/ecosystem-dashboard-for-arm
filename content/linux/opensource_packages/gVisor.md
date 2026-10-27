---
name: gVisor
category: Tool / Action Execution
description: gVisor is an Apache-2.0 Linux application sandbox with an OCI-compatible runtime for x86_64 and Arm64.
download_url: https://github.com/google/gvisor/releases
works_on_arm: true
supported_minimum_version:
  version_number: release-20210121.1
  release_date: 2021/01/28
optional_info:
  homepage_url: https://gvisor.dev/
  support_caveats: >-
    An aarch64 artifact is available for release-20210121.1 (2021/01/28),
    but the first Arm-supported release has not been established; the
    recorded minimum is not a verified first-support boundary. Modern
    releases require Linux 5.6+ and the complete runtime bundle, including
    gvisor-bin sidecars next to runsc. The systrap platform does not require
    KVM; the KVM platform requires host virtualization support and access
    to /dev/kvm. Not all Linux syscalls are supported.
  alternative_options: null
  getting_started_resources:
    official_docs: https://gvisor.dev/docs/user_guide/install/
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/serverless-on-arm64
    partner_content:
      - display_name: Linaro
        url: https://static.linaro.org/connect/lvc21f/presentations/LVC21F-204.pdf
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: >-
    Historical tag date:
    https://api.github.com/repos/google/gvisor/git/tags/7a132f373c4bf5317e27c76156cfb420703aa0c4
    and aarch64 artifact checksum:
    https://storage.googleapis.com/gvisor/releases/release/20210121.1/aarch64/runsc.sha512
    establish availability, not earliest support. Modern smoke baseline:
    release-20261019.0, published 2026/10/22, gvisor-aarch64.tar.bz2,
    SHA256 5790f89dc94b091b5aa0f0b6596aa4391606b3fe5f069e68f440576f3388abd8.
    Publisher checksums:
    https://github.com/google/gvisor/releases/download/release-20261019.0/SHA256SUMS
    OCI procedure: https://gvisor.dev/docs/user_guide/quick_start/oci/
    Platforms: https://gvisor.dev/docs/architecture_guide/platforms/
    License: https://github.com/google/gvisor/blob/release-20261019.0/LICENSE
---
