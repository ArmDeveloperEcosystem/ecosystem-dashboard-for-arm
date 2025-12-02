---
name: SPIRE
category: Security applications
description: SPIRE is a toolchain of APIs for establishing trust between software systems across a wide variety of hosting platforms.
download_url: https://github.com/spiffe/spire/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.6.4
    release_date: 2023/05/18


optional_info:
    homepage_url: https://spiffe.io/spire/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://spiffe.io/docs/latest/try/getting-started-linux-macos-x/
        arm_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/hardware-backed-security-multitenancy-edge-spiffe-parsec
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.8.0
        release_date: 2023/09/20
        reference_content: https://github.com/spiffe/spire/releases/tag/v1.8.0
        rationale: This version fixed an issue that prevented the server from running on Linux ARM64 when using SQLite.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/spiffe/spire/releases/tag/v1.6.4
    release_notes__recommended_minimum:
    other_info: Spire is the reference implementation of SPIFFE Project.

---
