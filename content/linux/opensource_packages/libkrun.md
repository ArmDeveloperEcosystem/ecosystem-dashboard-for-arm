---
name: "libkrun"
category: Containers and Orchestration
description: "libkrun is a dynamic library that provides a C API for virtualization-based process isolation."
download_url: "https://github.com/libkrun/libkrun/releases"
works_on_arm: true
supported_minimum_version:
  version_number: "0.1.3"
  release_date: "2021/01/27"
optional_info:
  homepage_url: "https://github.com/libkrun/libkrun"
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: null
    arm_content: null
    partner_content: null
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: "https://github.com/libkrun/libkrun/releases/tag/v0.1.3"
  release_notes__recommended_minimum: null
  support_context: >-
    Version 0.1.3 is the first numbered upstream tag containing commit
    66d16b58f3300de84900751a5a8a704a981e7291, which fixes functional Linux
    KVM/AArch64 support. This is an evidence-backed inference about the first
    functional tagged release, not a claim about the first inherited Arm code.
  other_info: >-
    The runtime requires hardware virtualization, usable /dev/kvm access,
    compatible libkrun firmware, and a guest root filesystem. The smoke baseline
    is v1.19.7 with pinned source, firmware, and a digest-pinned Alpine Arm64
    guest. Tests 1-5 require a real guest boot, guest architecture and I/O, and
    exit propagation. GitHub-hosted ubuntu-24.04-arm currently exposes no
    /dev/kvm, so the integration must stay draft until an approved Arm64 KVM
    runner executes the exact proposed bytes. SPDX Apache-2.0:
    https://github.com/libkrun/libkrun/blob/v1.19.7/LICENSE . Corrective commit:
    https://github.com/libkrun/libkrun/commit/66d16b58f3300de84900751a5a8a704a981e7291 .
    Tag comparisons:
    https://api.github.com/repos/libkrun/libkrun/compare/66d16b58f3300de84900751a5a8a704a981e7291...v0.1.1 ;
    https://api.github.com/repos/libkrun/libkrun/compare/66d16b58f3300de84900751a5a8a704a981e7291...v0.1.2 ;
    https://api.github.com/repos/libkrun/libkrun/compare/66d16b58f3300de84900751a5a8a704a981e7291...v0.1.3 .
    Baseline source commit 43b2f5aadeebb90f42053c9df2ec8b16583e554f;
    source archive SHA-256:
    7c31a3c62e696efbf13268ee6f37eb4740d82ea599dcd724525fe8f8f72729b0;
    firmware SHA-256:
    dea7905a167eee17d482200ea2fe15871aceb293b0674ac825ed7ae69759399f.
---
