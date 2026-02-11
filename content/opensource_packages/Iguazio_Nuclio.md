---
name: Nuclio
category: AI/ML
description: Nuclio by Iguazio is a high-performance serverless framework for real-time data and machine learning workloads. It enables developers to deploy inference functions with sub-second latency, making it ideal for integrating into AI pipelines and production-grade model serving. 
download_url: https://github.com/nuclio/nuclio/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.6.1
    release_date: 2021/02/19


optional_info:
    homepage_url: https://www.iguazio.com/open-source/nuclio/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/nuclio/nuclio#quick-start-steps
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.11.18
        release_date: 2023/05/04
        reference_content: https://github.com/nuclio/nuclio/releases/tag/1.11.18
        rationale: This version allows building nuclio services on arm64-based systems, fixes building java & go runtimes for arm, and also fixes building images for arm.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/nuclio/nuclio/releases/tag/1.6.0
    release_notes__recommended_minimum:
    other_info:

---
