---
name: SigNoz
category: Monitoring/Observability
description: SigNoz is an open-source observability platform that enables real-time monitoring and troubleshooting of applications through metrics, logs, and distributed tracing.
download_url: https://github.com/SigNoz/signoz/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.3.3
    release_date: 2021/08/03


optional_info:
    homepage_url: https://signoz.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://signoz.io/docs/install/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 0.76.0
        release_date: 2025/03/14
        reference_content: https://github.com/SigNoz/signoz/releases/tag/v0.76.0
        rationale: This version introduced a significant architectural update by consolidating the alert-manager, query-service, and frontend components into a single binary named signoz. This change simplifies deployment and may lead to performance improvements due to reduced inter-service communication overhead.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/SigNoz/signoz/releases/tag/v0.3.3
    release_notes__recommended_minimum:
    other_info:

---
