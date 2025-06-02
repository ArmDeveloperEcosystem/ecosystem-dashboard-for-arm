---
name: KubeVela
category: Containers and Orchestration
description: KubeVela is a modern application delivery platform that makes deploying and operating applications across today's hybrid, multi-cloud environments easier, faster and more reliable.
download_url: https://github.com/kubevela/kubevela/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.3.1
    release_date: 2021/01/29


optional_info:
    homepage_url: https://kubevela.io
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://kubevela.io/docs/
    arm_recommended_minimum_version:
        version_number: 1.8.0
        release_date: 2023/04/17
        reference_content: https://github.com/kubevela/kubevela/releases/tag/v1.8.0
        rationale: This version introduces Controller Sharding, enabling horizontal scaling of the control plane for multi-tenancy fairness, isolation, and system resilience. A comprehensive stability and scalability assessment showed KubeVela can handle over 400k applications under proper scaling, with improved memory and network efficiency. The release adds automatic SDK generation from definitions, simplifying integration with external Go/Java projects. KubeTrigger, a programmable CUE-based event system, allows dynamic reactions to filtered events within workflows. Finally, v1.8 integrates with Kruise Rollout to support automatic canary deployments, enabling fine-grained control of replicas and network traffic during progressive delivery.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/kubevela/kubevela/releases/tag/v0.3.1
    release_notes__recommended_minimum:
    other_info:
---
