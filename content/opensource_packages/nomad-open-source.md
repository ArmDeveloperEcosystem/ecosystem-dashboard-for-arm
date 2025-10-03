---
name: Nomad
category: Containers and Orchestration
description: Nomad is used for orchestration and management of application deployments, both containerized and non-containerized, across on-prem and cloud environments.
download_url: https://developer.hashicorp.com/nomad/install#linux
works_on_arm: true
supported_minimum_version:
    version_number: 0.8.6
    release_date: 2018/09/26


optional_info:
    homepage_url: https://www.hashicorp.com/products/nomad
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://developer.hashicorp.com/nomad/tutorials/get-started/gs-install
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.6.1
        release_date: 2023/07/21
        reference_content: https://github.com/hashicorp/nomad/releases/tag/v1.6.1
        rationale: This version uses config "cpu_total_compute" (if set) for all CPU statistics. Prior to this fix, CPU usage metrics on ARM servers were inaccurately reported, impacting scheduling and performance monitoring.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Downloaded furthest back version on GitHub v0.8.6 and found Arm support present.

---
