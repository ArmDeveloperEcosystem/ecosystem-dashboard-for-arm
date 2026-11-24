---
name: "Anthropic Sandbox Runtime"
draft: false
category: Identity & Security
description: "Anthropic Sandbox Runtime applies operating-system filesystem and network restrictions to agents, MCP servers, and arbitrary processes."
download_url: "https://www.npmjs.com/package/@anthropic-ai/sandbox-runtime?activeTab=versions"
works_on_arm: true
supported_minimum_version:
  version_number: "0.0.1"
  release_date: "2025/10/20"
optional_info:
  homepage_url: "https://github.com/anthropics/sandbox-runtime"
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: "https://github.com/anthropics/sandbox-runtime/blob/v0.0.81/README.md#unix-socket-restrictions-linux"
    arm_content: null
    partner_content: null
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: "https://www.npmjs.com/package/@anthropic-ai/sandbox-runtime/v/0.0.1"
  release_notes__recommended_minimum: null
  other_info: >-
    Version 0.0.1 is the first npm release and passed an SRI-verified native
    Arm64 compatibility probe. Upstream first documents Arm64 explicitly in
    v0.0.38, so 0.0.1 is a tested compatibility floor rather than a
    vendor-declared support boundary. Linux use requires Node.js, bubblewrap,
    socat, ripgrep, seccomp support, and permission to create the required
    namespaces. The smoke installs the SRI-verified v0.0.81 npm artifact with an
    integrity-locked dependency tree, verifies the AArch64 seccomp helper, and
    exercises command execution, filesystem controls, Unix-socket denial, and
    network denial. This compatibility check is not a security certification.
    SPDX Apache-2.0:
    https://github.com/anthropics/sandbox-runtime/blob/v0.0.81/LICENSE .
    Version 0.0.1 SRI:
    sha512-8ueLnIkkwirTXxVKBPpEUawb0Ql5sGWyCOEyuGWRQrY2I6f6ypBHuAXABiQISVVCGu8rbf9kHOnwJZJ9mLUnYA==.
    Version 0.0.81 SRI:
    sha512-bjHDu87gjIR7+Oxy9jPiK3v8CvSELCzfpXa3fjqfSKdvlZET2iF51xcXILWPayTpowB3xtZeQVf2JR916nVW/w==.
    First-release native proof:
    https://github.com/ranimandepudi/ecosystem-dashboard-for-arm/actions/runs/40567951981/job/122414153746 .
    Baseline native proof:
    https://github.com/ranimandepudi/ecosystem-dashboard-for-arm/actions/runs/41729146359 .
---
