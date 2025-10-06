---
name: Wasmtime
category: Runtimes
description: Wasmtime is a runtime for WebAssembly. It is fast, secure, configurable, supports a rich set of APIs, and compliant by standards.
download_url: https://github.com/bytecodealliance/wasmtime/releases
works_on_arm: true
supported_minimum_version:
  version_number: 0.16.0
  release_date: 2020/05/15
optional_info:
  homepage_url: https://wasmtime.dev/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://docs.wasmtime.dev/cli-install.html
    arm_content:
    partner_content:
      - display_name: Microsoft Azure
        url: https://opensource.microsoft.com/blog/2025/03/26/hyperlight-wasm-fast-secure-and-os-free/
  arm_recommended_minimum_version:
    version_number: 14.0.0
    release_date: 2023/10/20
    reference_content: https://github.com/bytecodealliance/wasmtime/releases/tag/v14.0.0
    rationale: This version introduced support for the v128 WebAssembly type on aarch64 architectures, enhancing Wasmtime's capabilities on ARM-based Linux systems.  The intention of this type is to allow platforms to perform typed between two functions that take or return v128 wasm values.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: Linux/ARM64 release notes are not available. The first AArch64 release (tar) is available in version 0.16.0. Binary inside this tar archive executes on Neoverse N1.
---
