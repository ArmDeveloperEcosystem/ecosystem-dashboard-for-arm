---
name: Maven
category: Compilers/Tools
description: Maven is a powerful build automation and project management tool primarily used in Java-based projects. Still, it can also be utilized with other programming languages and developed by the Apache Software Foundation.
download_url: https://github.com/apache/maven/releases
works_on_arm: true
supported_minimum_version:
  version_number: maven-3.6.0
  release_date: 2018/10/25
optional_info:
  homepage_url: https://maven.apache.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/microsoft-azure-preview-now-available-for-arm-neoverse
    partner_content:
      - display_name: Oracle OCI
        url: https://blogs.oracle.com/javamagazine/post/java-arm64-aarch64-development
      - display_name: Alibaba Cloud
        url: https://www.alibabacloud.com/help/en/acr/use-cases/build-and-push-multi-schema-images-locally-to-container-mirroring-service
    official_docs: https://maven.apache.org/download.cgi#Installation
  arm_recommended_minimum_version:
    version_number: 3.9.0
    release_date: 2023/02/14
    reference_content: https://maven.apache.org/docs/3.9.0/release-notes.html
    rationale: Minimum Java version to use with Maven 3.9.0 is raised to Java 8. This ensures full compatibility with Linux/Arm64 architecture.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://github.com/apache/maven/releases/tag/maven-3.6.0).
---
