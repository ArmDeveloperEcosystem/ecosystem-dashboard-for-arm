---
name: NVIDIA OpenShell
draft: false
category: Identity & Security
description: NVIDIA OpenShell is an open-source runtime that enforces filesystem, process, network, and credential policies for autonomous AI agents.
download_url: https://github.com/NVIDIA/OpenShell/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.0.6
    release_date: 2026/03/16
optional_info:
    homepage_url: https://docs.nvidia.com/openshell/latest/
    support_caveats_inline: true
    support_caveats: >-
        Linux Arm64 requires a supported runtime and the documented Landlock ABI 3+,
        seccomp, task-memory, and socket-binding capabilities; kernel version alone
        is insufficient. Docker requires Engine 28+; MicroVM requires KVM on Linux.
        Debian packages require glibc 2.28+. The Python package is an SDK, not the CLI.
        Historical minimum 0.0.6 is the first public launch release, not a deployment recommendation.
    getting_started_resources:
        official_docs: https://github.com/NVIDIA/OpenShell/blob/v0.1.6/docs/about/installation.mdx
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/NVIDIA/OpenShell/releases/tag/v0.0.6
    other_info: >-
        SPDX Apache-2.0: https://github.com/NVIDIA/OpenShell/blob/v0.1.6/LICENSE .
        Support: https://github.com/NVIDIA/OpenShell/blob/v0.1.6/docs/about/support-matrix.mdx .
        Launch: https://developer.nvidia.com/blog/run-autonomous-self-evolving-agents-more-safely-with-nvidia-openshell/ .
        NVIDIA launch-version statement, GTC S81765 at 20:36-20:47:
        https://www.nvidia.com/en-us/on-demand/session/gtc26-s81765/ .
        First public release support matrix:
        https://github.com/NVIDIA/OpenShell/blob/v0.0.6/docs/reference/support-matrix.md .
        v0.0.6 publication 2026-03-16T14:57:48Z:
        https://github.com/NVIDIA/OpenShell/releases/tag/v0.0.6 .
        v0.1.6 publication 2026-10-27T17:56:58Z; baseline, not historical minimum.
        Debian SHA256 2f6e2b7b09399d91443fc8e25bd5db360dfee562db17bb2778ac0d0067969f85.
        Runtime images resolve versioned tags to immutable digests per run; the
        resulting digests are logged, not claimed historically immutable tag mappings.
        The smoke uses Docker without KVM and requires sandbox create, native exec,
        a filesystem deny with a same-UID writable control, and confirmed deletion.
        Missing prerequisites fail the baseline; newer-version regression is explicitly
        deferred with runtime_validation_not_automated. No performance recommendation asserted.
        No native run or performance result is borrowed from upstream.
---
