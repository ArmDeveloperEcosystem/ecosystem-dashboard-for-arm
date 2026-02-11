---
name: Spring Cloud Netflix
category: Miscellaneous
description: Spring Cloud Netflix is a collection of tools for building microservices, providing features like service discovery, load balancing, and fault tolerance.
download_url: https://github.com/spring-cloud/spring-cloud-netflix/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.2.5.RELEASE
    release_date: 2017/02/03
 
 
optional_info:
    homepage_url: https://spring.io/projects/spring-cloud-netflix
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/spring-cloud/spring-cloud-netflix
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 4.1.2
        release_date: 2024/05/30
        reference_content: https://github.com/spring-cloud/spring-cloud-netflix/releases/tag/v4.1.2
        rationale: This release introduces improved observability with Eureka Server Micrometer metrics for registered services and enhanced event ordering. It also adds missing observability support in RestTemplateTransportClientFactory. Bug fixes include resolving a shutdown exception introduced in 4.1.1 and correcting basic auth failures when using encoded characters.
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info:  Linux/ARM64 release notes are not available. Version "1.2.5.RELEASE" has been successfully installed on the Neoverse N1, prior versions are failing to build.
 
---
