---
name: Tiffin
category: Security applications
description: Tiffin is a lightweight Rust library for creating and managing chroot jails on Linux, enabling simple filesystem isolation for security and sandboxing.
download_url: https://github.com/FyraLabs/tiffin/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.3.1
    release_date: 2024/07/19


optional_info:
    homepage_url: https://github.com/FyraLabs/tiffin
    support_caveats: Earlier versions such as 0.0.1 build successfully on Linux/Arm64, but only 0.3.1 and later are officially released.
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/FyraLabs/tiffin#readme
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no platform-specific release notes for Linux/Arm64 or additional documentation available on GitHub. Since a `Cargo.toml` file is provided, version 0.3.1 can be built using `cargo build --release` and tested with `cargo test -- --ignored`. Earlier commit-based versions, such as 0.0.1, have also been tested and confirmed to build on Arm64.

---
