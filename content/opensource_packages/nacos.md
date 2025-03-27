---
name: Nacos
category: Service Mesh
description: Nacos is an open-source platform designed for managing and discovering services in cloud-native applications.
download_url: https://github.com/alibaba/nacos/tags
works_on_arm: true
supported_minimum_version:
    version_number: 2.1.1
    release_date: 2022/08/08

optional_info:
    homepage_url: https://nacos.io/
    support_caveats: For Nacos to run on ARM servers, Java 8 or above must be installed. Lower versions do not support Nacos on ARM64.
    alternative_options: 
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://nacos.io/en-us/docs/quick-start.html
    arm_recommended_minimum_version:
        version_number: 
        release_date:
        reference_content:
        rationale:


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: There are no release notes or binaries present for Linux/ARM64. Nacos version 2.1.1 is installed and tested on the Neoverse N1, using steps mentioned [here](https://nacos.io/en-us/docs/quick-start.html). Specifically, version 2.1.0 was the last version that did not build on ARM64 servers.

---
