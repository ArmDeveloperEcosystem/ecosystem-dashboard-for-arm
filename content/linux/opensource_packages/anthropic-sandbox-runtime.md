---
name: Anthropic Sandbox Runtime
draft: false
category: Identity & Security
description: Anthropic Sandbox Runtime (srt) applies OS-level filesystem and network restrictions to agents, MCP servers, and arbitrary processes using bubblewrap on Linux.
download_url: https://www.npmjs.com/package/@anthropic-ai/sandbox-runtime?activeTab=versions
works_on_arm: true
supported_minimum_version:
    version_number: 0.0.1
    release_date: 2025/10/20
optional_info:
    homepage_url: https://github.com/anthropics/sandbox-runtime
    support_caveats_inline: true
    support_caveats: >-
        Version 0.0.81 on Linux Arm64 requires Node.js 22.12+, bubblewrap, socat,
        ripgrep, seccomp, and working nested user, PID, mount, and network namespaces.
        Ubuntu 24.04 AppArmor policy can block the required user namespaces.
        Historical minimum 0.0.1 (2025-10-20) is the first published release,
        not a deployment recommendation.
    getting_started_resources:
        official_docs: https://github.com/anthropics/sandbox-runtime/blob/v0.0.81/README.md
optional_hidden_info:
    release_notes__supported_minimum: https://www.npmjs.com/package/@anthropic-ai/sandbox-runtime/v/0.0.1
    other_info: >-
        SPDX Apache-2.0: https://github.com/anthropics/sandbox-runtime/blob/v0.0.81/LICENSE .
        Initial source: https://github.com/anthropics/sandbox-runtime/tree/b483c6113b5a7f05d32eec16ba61734ce9bf597c .
        Arm evidence by v0.0.38: https://github.com/anthropics/sandbox-runtime/blob/v0.0.38/README.md .
        GitHub v0.0.38 publication 2026-02-19T22:55:37Z; v0.0.81 publication
        2026-10-20T01:01:41Z: https://github.com/anthropics/sandbox-runtime/releases/tag/v0.0.81 .
        These are GitHub release timestamps, not npm publication timestamps.
        Registry publication evidence: https://github.com/ranimandepudi/ecosystem-dashboard-for-arm/actions/runs/40566400512 ,
        job npm-publication-evidence; source https://registry.npmjs.org/@anthropic-ai%2fsandbox-runtime .
        Registry response SHA256 369f018fa73fbeaac402e8e1d320d49f5f0bb15882e4d053bd609a23ff13e957.
        npm created 2025-10-20T17:36:42.320Z; 0.0.1 published 2025-10-20T17:36:42.705Z;
        0.0.81 published 2026-10-20T01:13:23.926Z. No cpu/os restrictions on either version.
        0.0.1 SRI sha512-8ueLnIkkwirTXxVKBPpEUawb0Ql5sGWyCOEyuGWRQrY2I6f6ypBHuAXABiQISVVCGu8rbf9kHOnwJZJ9mLUnYA==.
        0.0.81 SRI sha512-bjHDu87gjIR7+Oxy9jPiK3v8CvSELCzfpXa3fjqfSKdvlZET2iF51xcXILWPayTpowB3xtZeQVf2JR916nVW/w==.
        Canonical npm package @anthropic-ai/sandbox-runtime, executable srt.
        The smoke installs the SRI-verified 0.0.81 npm tarball with lifecycle scripts
        disabled and Node 22.21.1 checksum pinned. Declared transitive dependency
        versions are resolved by npm at run time, not fixed by a checked-in lockfile.
        The installed Arm64 seccomp helper must be present and have AArch64 ELF identity.
        Mandatory execution, filesystem, AF_UNIX, and proxy deny-all checks fail on
        unavailable prerequisites. Only the disposable runner's documented AppArmor
        sysctl is adjusted, with restoration required. No weaker sandbox or disabled
        seccomp is used. Newer-version regression is deferred with runtime_validation_not_automated.
        First-release native proof:
        https://github.com/ranimandepudi/ecosystem-dashboard-for-arm/actions/runs/40567951981/job/122414153746 .
        On Linux AArch64 with Node 22.21.1, the SRI-verified npm 0.0.1 artifact
        passed manifest identity, stdin/stdout, allowed reads/writes, denied secret
        masking, descendant process I/O, and denied writes. Its CLI incorrectly
        hardcodes 1.0.0; package.json plus SRI establish version 0.0.1.
        This historical compatibility check is not a security certification.
        Arm CI evidence: https://github.com/anthropics/sandbox-runtime/blob/v0.0.81/.github/workflows/integration-tests.yml .
        No native run or performance result is borrowed from upstream.
---
