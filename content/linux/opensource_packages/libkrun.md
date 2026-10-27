---
name: libkrun
category: Containers and Orchestration
description: libkrun is a dynamic library providing a C API for virtualization-based process isolation.
download_url: https://github.com/libkrun/libkrun/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.1.3
    release_date: 2021/01/27

optional_info:
    homepage_url: https://github.com/libkrun/libkrun
    support_caveats_inline: true
    support_caveats: "Linux Arm64 guest execution requires hardware virtualization and usable read/write /dev/kvm access, matching libkrunfw firmware and a guest root filesystem. VM-backed hosts must expose nested virtualization; passing /dev/kvm into a container cannot create missing host virtualization. Apply host isolation when exposing files through virtio-fs; the library alone does not protect unrelated host files. Version 0.1.3 is the first numbered upstream tag containing the functional KVM/AArch64 fix. This supports the first-functional-support minimum as an inference, not a claim about the initial introduction of inherited Arm code."
    getting_started_resources:
        official_docs: https://github.com/libkrun/libkrun/blob/v1.19.7/README.md#building-and-installing

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/libkrun/libkrun/releases/tag/v0.1.3
    other_info: "SPDX: Apache-2.0, verified in https://github.com/libkrun/libkrun/blob/v1.19.7/LICENSE. Canonical repository libkrun/libkrun; containers/libkrun redirects here. Linux Arm64 corrective evidence: https://github.com/libkrun/libkrun/commit/66d16b58f3300de84900751a5a8a704a981e7291 (2021-01-11), which says inherited AArch64 support was preserved but untested. The complete current inventory of 71 public tags establishes the numbered-tag boundary: v0.1.1 is six commits before the fix, v0.1.2 is four commits before it, and v0.1.3 is 32 commits after it. Compare evidence: https://api.github.com/repos/libkrun/libkrun/compare/66d16b58f3300de84900751a5a8a704a981e7291...v0.1.1 ; https://api.github.com/repos/libkrun/libkrun/compare/66d16b58f3300de84900751a5a8a704a981e7291...v0.1.2 ; https://api.github.com/repos/libkrun/libkrun/compare/66d16b58f3300de84900751a5a8a704a981e7291...v0.1.3 . The v0 tag aliases v0.1.5 rather than an earlier release. Accordingly v0.1.3 is the first numbered upstream tag containing the functional KVM/AArch64 fix, supporting first functional Linux Arm64 support as an explicit inference rather than initial inherited-code introduction. Cargo still declared 0.1.1 at v0.1.3, so Cargo metadata is not the release-tag boundary. No Arm performance recommendation established. Smoke baseline 1.19.7 (2026-10-22), source commit 43b2f5aadeebb90f42053c9df2ec8b16583e554f; the commit-addressed source archive SHA-256 is independently calculated, not an upstream signature. Source-only release; firmware pinned to libkrunfw v5.6.2 with its upstream asset SHA-256. The guest probe exports a digest-pinned official Alpine 3.22.2 Arm64 image using an accessible Docker daemon, boots via the library C API, verifies guest architecture and file I/O, and requires guest exit 23 to propagate. Upstream integration coverage: https://github.com/libkrun/libkrun/blob/v1.19.7/.github/workflows/integration_tests.yml; this is not evidence that our workflow booted a guest. Implementation status: the package workflow mandates guest execution and fails without usable KVM. The checked ubuntu-24.04-arm hosted runner lacks /dev/kvm; no native guest success is claimed. Keep integration draft until a reviewed KVM execution path preserves the batch topology guard. Version/help/doctor or API-only checks cannot establish guest execution."
---
