---
name: Dynatrace-Operator (Dynatrace)
category: Monitoring/Observability
description: The Dynatrace Operator is a Kubernetes operator provided by Dynatrace that automates the deployment, configuration, and management of Dynatrace monitoring components within Kubernetes clusters.
download_url: https://github.com/Dynatrace/dynatrace-operator/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.1.0
    release_date: 2021/01/18


optional_info:
    homepage_url: https://www.dynatrace.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/Dynatrace/dynatrace-operator#installation
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 0.14.0
        release_date: 2023/10/13
        reference_content: https://docs.dynatrace.com/docs/whats-new/release-notes/dynatrace-operator/dto-fix-0-14-0
        rationale: In this version, default tolerations were added for ActiveGate pods, allowing them to be scheduled on both Amd64 and Arm64 nodes for broader deployment compatibility.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes to mark the initial Linux/Arm64 support. However, Dynatrace-Operator Docker images for Arm64 are available from the first version 0.1.0 onwards at [DockerHub](https://hub.docker.com/r/dynatrace/dynatrace-operator/tags?name=0.1.0).
  
---
