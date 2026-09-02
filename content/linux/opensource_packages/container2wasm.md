---
name: Container2Wasm
category: Containers and Orchestration
description: Container2Wasm is a tool that converts container images into WebAssembly (Wasm) format, enabling them to run on WASI runtimes or in browsers using emulation.
download_url: https://github.com/container2wasm/container2wasm/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.1.0
    release_date: 2023/02/28
 
 
optional_info:
    homepage_url: https://github.com/container2wasm/container2wasm
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/container2wasm/container2wasm#examples
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 0.8.3
        release_date: 2025/07/28
        reference_content: https://github.com/container2wasm/container2wasm/releases/tag/v0.8.3
        rationale: In this relese, stack size exceeded error when running Aarch64 guest on Safari was fixed.
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: The release notes for the initial Linux/Arm64 support aren't available. The initial version rolls out Linux/Arm64 artifacts.
 
---
