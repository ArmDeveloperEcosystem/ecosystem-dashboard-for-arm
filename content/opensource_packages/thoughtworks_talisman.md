---
name: Thoughtworks Talisman
category: Security applications
description: ThoughtWorks Talisman is an open-source security tool designed to prevent the accidental inclusion of sensitive information in git repositories.
download_url: https://github.com/thoughtworks/talisman/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.28.1
    release_date: 2022/08/13


optional_info:
    homepage_url: https://thoughtworks.github.io/talisman/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://thoughtworks.github.io/talisman/docs/installation
    arm_recommended_minimum_version:
        version_number: 1.37.0
        release_date: 2025/05/02
        reference_content: https://github.com/thoughtworks/talisman/releases/tag/v1.37.0
        rationale: This version includes several dependency upgrades and maintenance improvements. Key Go libraries such as logrus, testify, afero, pb/v3, pflag, and golang/mock were updated for improved stability and feature support. The gofmt formatting violations were fully resolved, and legacy integration with codecov.io was removed. Additionally, the uv.lock file was added to recognized Python scopes, ensuring smoother tooling compatibility.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes available for Linux/ARM64. However, the first Linux/ARM64 binary release is rolled out in [v1.28.1](https://github.com/thoughtworks/talisman/releases/tag/v1.28.1).

---
