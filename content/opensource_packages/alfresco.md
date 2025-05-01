---
name: Alfresco Content Services
category: Content mgmt platforms
description: Alfresco Content Services is an open-source Enterprise Content Management (ECM) platform enabling organizations to manage, store, collaborate, and automate workflows around digital content such as documents and records. It supports seamless integration with enterprise systems, cloud services, and third-party tools.
download_url: https://hub.docker.com/r/alfresco/alfresco-content-repository-community/tags
works_on_arm: true
supported_minimum_version:
    version_number: 7.3
    release_date: 2022/11/16


optional_info:
    homepage_url: https://www.hyland.com/en/solutions/products/alfresco-platform
    support_caveats: PDF renderer is not supported on Arm64; use alternatives or build manually. LibreOffice and ImageMagick must be installed separately as they are not bundled for Arm64.
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content: 
        official_docs: https://docs.alfresco.com/content-services/latest/
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum: https://connect.hyland.com/t5/alfresco-blog/alfresco-7-3-alfresco-docker-images-aarch64-arm64-support/ba-p/123654
    release_notes__recommended_minimum:
    other_info: Version 7.3 introduced official Arm64 support via Docker images and is suitable for production use on Arm systems.

---
