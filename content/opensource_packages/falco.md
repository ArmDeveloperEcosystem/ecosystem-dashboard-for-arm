---
name: Falco
category: Security applications
description: Falco is a cloud native runtime security tool for Linux operating systems.
download_url: https://falco.org/docs/install-operate/download/
works_on_arm: true
supported_minimum_version:
    version_number: 0.32.1
    release_date: 2022/07/11


optional_info:
    homepage_url: https://falco.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content: https://aws.amazon.com/blogs/containers/implementing-runtime-security-in-amazon-eks-using-cncf-falco/
        official_docs: https://falco.org/docs/install-operate/installation/
    arm_recommended_minimum_version:
        version_number: 0.39.2
        release_date: 2024/11/21
        reference_content: https://github.com/falcosecurity/falco/releases/tag/0.39.2
        rationale: This version introduces Arm64 CNCF runners in Falco's CI pipeline, ensuring builds are continuously validated on Arm64. While not a runtime optimization, this version marks Arm64 as a first-class supported platform, improving stability and reliability for Linux Arm64 users.


optional_hidden_info:
    release_notes__supported_minimum: https://falco.org/blog/falco-0-32-1/
    release_notes__recommended_minimum:
    other_info:

---
