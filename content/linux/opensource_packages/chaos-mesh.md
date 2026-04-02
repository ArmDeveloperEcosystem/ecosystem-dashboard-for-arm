---
name: Chaos Mesh
category: Monitoring/Observability
description: Chaos Mesh is an open source cloud-native Chaos Engineering platform. It offers various types of fault simulation.
download_url: https://github.com/chaos-mesh/chaos-mesh/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.1.2
    release_date: 2021/03/12

optional_info:
    homepage_url: https://chaos-mesh.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://chaos-mesh.org/docs/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.3.0
        release_date: 2022/07/29
        reference_content: https://github.com/chaos-mesh/chaos-mesh/releases/tag/v2.3.0
        rationale: This release introduces AArch64 support for TimeChaos and a new BlockChaos implementation in chaos-daemon, expanding chaos testing capabilities. Significant Helm chart enhancements include improved update strategies, PSP policy relaxation, and OpenAPI-based client updates. Several bug fixes were applied, including compatibility with Kubernetes >1.24 and stability improvements across JVMChaos, NetworkChaos, and StressChaos. ARM support is reinforced with new integration tests and cleanup of ARM-specific CI and scripts.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/chaos-mesh/chaos-mesh/releases/tag/v1.1.2
    release_notes__recommended_minimum:
    other_info:

---
