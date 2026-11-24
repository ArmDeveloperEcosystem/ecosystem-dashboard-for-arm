---
name: "NVIDIA OpenShell"
category: Identity & Security
description: "NVIDIA OpenShell is an open-source runtime that enforces filesystem, process, network, and credential policies for autonomous AI agents."
download_url: "https://github.com/NVIDIA/OpenShell/releases"
works_on_arm: true
supported_minimum_version:
  version_number: "0.0.6"
  release_date: "2026/03/16"
optional_info:
  homepage_url: "https://docs.nvidia.com/openshell/latest/"
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: "https://github.com/NVIDIA/OpenShell/blob/v0.1.6/docs/about/support-matrix.mdx"
    arm_content: "https://learn.arm.com/install-guides/openshell/"
    partner_content: null
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: "https://github.com/NVIDIA/OpenShell/releases/tag/v0.0.6"
  release_notes__recommended_minimum: null
  other_info: >-
    Version 0.0.6 is the first public launch release with Linux AArch64 support,
    not a deployment recommendation. Container sandboxes require the documented
    Linux security facilities; the microVM backend additionally requires KVM.
    The smoke baseline is v0.1.6. It uses immutable Arm64 Debian and container
    artifacts, creates a real sandbox, verifies native execution, enforces a
    filesystem denial with a writable control, and confirms deletion. Test 6 is
    explicitly deferred because a newer release requires a separately pinned
    full runtime bundle and the same end-to-end enforcement probe. Historical
    support matrix:
    https://github.com/NVIDIA/OpenShell/blob/v0.0.6/docs/reference/support-matrix.md .
    NVIDIA launch-version statement, GTC S81765 at 20:36-20:47:
    https://www.nvidia.com/en-us/on-demand/session/gtc26-s81765/ . SPDX
    Apache-2.0: https://github.com/NVIDIA/OpenShell/blob/v0.1.6/LICENSE .
    Baseline Debian SHA-256:
    2f6e2b7b09399d91443fc8e25bd5db360dfee562db17bb2778ac0d0067969f85.
    Sandbox image digest:
    sha256:1038eb5c1f191fa3c34684fd7041b891c78ec570979d487f36e06e08f91bfb63;
    supervisor image digest:
    sha256:ce859a7d77ee515d3fe0b3c7dc61286516f402eb1d25c761d806d9ae5ed96c0b;
    Arm64 workload image digest:
    sha256:d9461f428eea54e553add3a5158a0f245c6e1ea73efc59fff8e98e3d4a38e378.
---
