---
name: Spring Cloud Gateway
category: Networking
description: Spring Cloud Gateway is an open-source API gateway framework, part of the broader Spring Cloud ecosystem. It provides a simple, scalable solution for routing and filtering requests in microservice architectures.
download_url: https://github.com/spring-cloud/spring-cloud-gateway/releases
works_on_arm: true
supported_minimum_version:
    version_number: 3.1.2
    release_date: 2022/04/27


optional_info:
    homepage_url: https://spring.io/projects/spring-cloud-gateway
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://cloud.spring.io/spring-cloud-gateway/reference/html/
    arm_recommended_minimum_version:
        version_number: 4.1.2
        release_date: 2024/03/27
        reference_content: https://github.com/spring-cloud/spring-cloud-gateway/releases/tag/v4.1.2
        rationale: Spring Cloud Gateway introduced several enhancements in this version, including the ability to disable filters and headers via properties, support for @Order in global and gateway filters, and improvements to filter configuration using the Java DSL. It added AOT support for Gateway MVC and updated the dashboard to Grafana 9.x. Other highlights include enabling random-aware WeightCalculatorWebFilter, public access to key constants, and a new Mono-returning method for better reactive handling.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://github.com/spring-cloud/spring-cloud-gateway/releases/tag/v3.1.2).

---

