---
name: Junit5
category: Miscellaneous
description: JUnit5 is the latest major version of the JUnit testing framework, which is used for writing and running unit tests in Java. JUnit5 is designed to address the limitations of previous versions while providing new features and enhancements that make writing and running tests more efficient and powerful.
download_url: https://github.com/junit-team/junit5/releases
works_on_arm: true
supported_minimum_version:
    version_number: 5.9.0
    release_date: 2022/07/26


optional_info:
    homepage_url: https://junit.org/junit5/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/junit-team/junit5?tab=readme-ov-file#building-from-source
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes. Version 5.9.0 can be built on Neoverse N1 using "gradlew clean assemble" command. Prior versions are failing to build collectively on both ARM64 and AMD64.

---
