---
name: Kube-bench
category: Security applications
description: kube-bench is a tool that checks whether Kubernetes is deployed according to security best practices as defined in the CIS Kubernetes Benchmark.
download_url: https://github.com/aquasecurity/kube-bench/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.3.1
    release_date: 2020/07/10


optional_info:
    homepage_url: https://www.aquasec.com/products/open-source-projects/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://aquasecurity.github.io/kube-bench/dev/installation/
    arm_recommended_minimum_version:
        version_number: 0.6.6
        release_date: 2022/01/12
        reference_content: https://github.com/aquasecurity/kube-bench/releases/tag/v0.6.6
        rationale: Linux/ARM64 artifacts were released in prior versions, but official ARM64 support is declared in version 0.6.6. Numerous dependency upgrades were made, including golang, gorm, client-go, and aws-sdk-go, improving performance and security.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/aquasecurity/kube-bench/releases/tag/v0.3.1
    release_notes__recommended_minimum:
    other_info:
---
