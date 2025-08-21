---
name: Gerrit
category: Miscellaneous
description: Gerrit is a project management and code review tool for Git projects.
download_url: https://github.com/GerritCodeReview/gerrit/tags
works_on_arm: true
supported_minimum_version:
    version_number: 3.4.8
    release_date: 2022/11/08


optional_info:
    homepage_url: https://gerrit.googlesource.com/gerrit
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/GerritCodeReview/gerrit#build
    arm_recommended_minimum_version:
        version_number: 3.8.0
        release_date: 2023/05/19
        reference_content: https://www.gerritcodereview.com/3.8.html#native-packaging
        rationale: OS base images for Gerrit's AlmaLinux and Ubuntu Docker images have been upgraded to version 9.1 ans 22 respectively in Gerrit version 3.8.0. This ensures compatibility with the newer software stack.

optional_hidden_info:
    release_notes__supported_minimum: https://gitenterprise.me/2022/11/23/arm-64-welcomes-gerrit-code-review/
    release_notes__recommended_minimum:
    other_info: GerritForge RPM repository has been updated for the Arm64 architecture, and the Gerrit Docker image is available for Linux/Arm64 from version 3.4.8 onwards.

---
