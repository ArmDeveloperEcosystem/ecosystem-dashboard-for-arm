---
name: Spring Boot
category: Runtimes
description: Spring Boot is an open-source Java-based framework used to create standalone, production-grade Spring-based applications with minimal setup and configuration.
download_url: https://github.com/spring-projects/spring-boot/releases
works_on_arm: true
supported_minimum_version:
  version_number: 1.0.0
  release_date: 2023/09/12
optional_info:
  homepage_url: https://spring.io/projects/spring-boot
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/containers/optimize-your-spring-boot-application-for-aws-fargate/
    official_docs: https://spring.io/quickstart
  arm_recommended_minimum_version:
    version_number: 3.4.0
    release_date: 2024/11/21
    reference_content: https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.4-Release-Notes
    rationale: Spring Boot 3.4.0 introduced the capability to create multi-architecture OCI images, facilitating deployments across different platforms, including ARM architectures.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: No ARM64 specific release notes and binaries are available. Installation and testing is done using released source code tar.
---
