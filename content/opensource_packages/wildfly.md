---
name: WildFly
category: Web Server
description: WildFly is a powerful, modular and lightweight application server that helps to build amazing applications.
download_url: https://github.com/wildfly/wildfly/tags
works_on_arm: true
supported_minimum_version:
    version_number: 18.0.1
    release_date: 2019/11/15


optional_info:
    homepage_url: https://www.wildfly.org/
    support_caveats: As a Java-based platform, this package will run on top of an Arm compatible JVM.
    alternative_options:
    getting_started_resources:
        arm_content:  
        partner_content: 
        official_docs: https://github.com/wildfly/wildfly/blob/main/README.md
    arm_recommended_minimum_version:
        version_number: 26.1.1.Final-2
        release_date: 2022/11/10
        reference_content: https://www.wildfly.org/news/2022/11/10/wildfly-docker-temurin/
        rationale: This update introduces multi-architecture support, with WildFly images now available for both linux/arm64 and linux/amd64 platforms. It includes support for LTS versions of JDK 11 and 17, as well as the latest non-LTS JDK (currently JDK 19). The base images are regularly updated to address OS and JDK security vulnerabilities, ensuring improved compatibility and security across environments.

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum: 
    other_info: There are no release notes or binaries present for Linux/ARM64. Wildfly 18.0.1 is successfully installed and tested on the Neoverse N1, following the steps mentioned in [README.md](https://github.com/wildfly/wildfly/blob/18.0.0.Final/README.md).

---
