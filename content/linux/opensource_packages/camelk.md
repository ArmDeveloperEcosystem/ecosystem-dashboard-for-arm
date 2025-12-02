---
name: Apache Camel K
category: DevOps
description: Camel K is a Kubernetes operator that automates the build, deployment, and management of Apache Camel integrations on cloud-native platforms. It supports advanced features like environment promotion, monitoring, scaling, Knative and Kafka integration, and resource tuning.
download_url: https://github.com/apache/camel-k/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.0.0
    release_date: 2023/07/24


optional_info:
    homepage_url: https://camel.apache.org/camel-k/latest/concepts/overview.html
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://camel.apache.org/camel-k/latest/installation/installation.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.6.0
        release_date: 2025/02/15
        reference_content: https://camel.apache.org/releases/k-2.6.0/
        rationale: In this elease, Arm64 support is explicitly being tested and integrated into the CI pipeline, which gives a stronger baseline for Arm-optimized and Arm-validated builds.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/apache/camel-k/releases/tag/v2.0.0
    release_notes__recommended_minimum:
    other_info: Official Docker images for Linux/Arm64 have been published on Docker Hub starting with version 2.0.0.

---
