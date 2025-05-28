---
name: Kyverno
category: Security applications
description: Security applications
download_url: https://github.com/kyverno/kyverno/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.6.0
    release_date: 2022/02/08


optional_info:
    homepage_url: https://kyverno.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://kyverno.io/docs/installation/methods/
    arm_recommended_minimum_version:
        version_number: 1.10.0
        release_date: 2023/05/30
        reference_content: https://github.com/kyverno/kyverno/releases/tag/v1.10.0
        rationale: Kyverno 1.10 is a major breaking release that decomposes the application into three controllers - admission, background, and reporting. It introduces Notary signature verification, intra-cluster service calls, and extensive changes to generate and mutate policies, including stricter validation and immutability enforcement. There is no direct upgrade path for YAML installs and only a limited Helm upgrade via a new upgrade.fromV2 flag; manual backup is required. Mutation logic was redesigned for clarity and sequencing, and a new image_normalize() JMESPath filter improves container image handling. The release adds support for subresource triggers, context variable lazy loading, Helm v3 enhancements, and Kubernetes 1.27 testing. Many new configuration options and flags improve policy management, logging, controller isolation, and performance observability.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/kyverno/kyverno/releases/tag/v1.6.0
    release_notes__recommended_minimum:
    other_info: No ARM64 specific release notes available but tar file is released for ARM64 from v1.6.0.

---
