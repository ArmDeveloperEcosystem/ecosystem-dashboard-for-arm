---
name: SonarQube Server
category: DevOps
description: SonarQube Server is an automated code review and static analysis tool, that can integrate directly with the CI pipeline or the supported DevOps platforms, and can detect coding issues against an extensive set of rules.
download_url: https://hub.docker.com/_/sonarqube/tags
works_on_arm: true
supported_minimum_version:
    version_number: 9.9.0
    release_date: 2023/04/27


optional_info:
    homepage_url: https://docs.sonarsource.com/sonarqube-server/latest/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://docs.sonarsource.com/sonarqube-server/latest/setup-and-upgrade/install-the-server/installing-sonarqube-from-docker/
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no official release notes to support Linux/ARM64. However, SonarQube server can be installed via the docker image, which is available for Linux/ARM64 from version 9.9 onwards. Kindly refer [here](https://hub.docker.com/_/sonarqube/tags).

---
