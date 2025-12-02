---
name: AdoptOpenJDK
category: Miscellaneous
description: AdoptOpenJDK is an open-source project that provides prebuilt OpenJDK binaries for various platforms.
download_url: https://adoptium.net/temurin/releases
works_on_arm: true
supported_minimum_version: 
    version_number: jdk8u-2021-01-31-20-36
    release_date: 2021/02/01


optional_info:
    homepage_url: https://adoptium.net/
    support_caveats: AdoptOpenJDK has transitioned to the Eclipse Foundation under the Adoptium project. Starting with the July 2021 releases, future builds are available from [Adoptium.net](https://adoptium.net/) under the new name Eclipse Temurin.
    alternative_options:
    getting_started_resources:
        official_docs: https://adoptium.net/docs
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 21
        release_date: 2024/08/09
        reference_content: https://adoptium.net/news/2024/08/adoptium-reproducible-verification-builds
        rationale: Eclipse Temurin JDK 21+ releases are now fully reproducible for many platforms, including Linux AArch64. This ensures nothing malicious or unexpected is embedded in the binaries. This is a major milestone for transparency, security, and trustworthiness, especially for environments like Linux/Arm64 where deterministic builds can reduce platform-specific bugs.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/AdoptOpenJDK/openjdk8-binaries/releases/tag/jdk8u-2021-01-31-20-36
    release_notes__recommended_minimum: 
    other_info: 

---
