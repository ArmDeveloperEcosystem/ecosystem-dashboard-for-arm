---
name: Gardener autoscaler
category: Containers and Orchestration
description: Gardener Autoscaler is a fork of the Kubernetes autoscaler adapted for the Gardener ecosystem, adding support for Machine Controller Manager (MCM) to automatically scale Kubernetes clusters across multiple cloud providers.
download_url: https://console.cloud.google.com/artifacts/docker/gardener-project/europe/releases/gardener%2Fautoscaler%2Fcluster-autoscaler
works_on_arm: true
supported_minimum_version:
    version_number: 1.20.4
    release_date: 2023/01/16
 
 
optional_info:
    homepage_url: https://github.com/gardener/autoscaler
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/gardener/autoscaler#getting-the-code
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.26.0
        release_date: 2023/03/27
        reference_content: https://github.com/gardener/autoscaler/releases/tag/v1.26.0
        rationale: In this release, docker images for cluster-autoscaler are published with multi-arch support for linux/Arm64.
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/gardener/autoscaler/releases/tag/v1.20.4
    release_notes__recommended_minimum:
    other_info:
 
---
