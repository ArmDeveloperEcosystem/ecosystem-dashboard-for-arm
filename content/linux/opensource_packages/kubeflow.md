---
name: Kubeflow
category: Containers and Orchestration
description: Kubeflow the cloud-native platform for machine learning operations - pipelines, training and deployment.
download_url: https://github.com/kubeflow/kubeflow/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.8.0
    release_date: 2023/11/01


optional_info:
    homepage_url: https://www.kubeflow.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://www.kubeflow.org/docs/started/installing-kubeflow/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.9.0
        release_date: 2024/07/22
        reference_content: https://blog.kubeflow.org/kubeflow-1.9-release/
        rationale: This version introduced New Tools for Model Management and Training Optimization, including model registry, Fine-Tune APIs for LLMs, security enhancements like Oauth2-proxy and CVE scanning, improved integrations with Ray, Seldon, BentoML, and KServe for LLM GPU optimizations, etc.


optional_hidden_info:
    release_notes__supported_minimum: https://blog.kubeflow.org/kubeflow-1.8-release/
    release_notes__recommended_minimum:
    other_info: The Project previously used to release linux binaries for x86 although now only tar and zip files are being released.

---
