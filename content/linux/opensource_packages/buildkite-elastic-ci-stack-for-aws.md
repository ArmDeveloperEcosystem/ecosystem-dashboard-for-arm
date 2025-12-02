---
name: Buildkite Elastic CI Stack for AWS
category: DevOps
description: The Buildkite Elastic CI Stack for AWS is a CloudFormation stack that simplifies the process of setting up a scalable, secure, and highly available CI/CD infrastructure on Amazon Web Services (AWS).
download_url: https://github.com/buildkite/elastic-ci-stack-for-aws/releases
works_on_arm: true
supported_minimum_version:
    version_number: 5.1.0
    release_date: 2020/12/11


optional_info:
    homepage_url: https://buildkite.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://buildkite.com/docs/agent/v3/elastic-ci-aws
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 6.29.0
        release_date: 2024/10/09
        reference_content: https://github.com/buildkite/elastic-ci-stack-for-aws/releases/tag/v6.29.0
        rationale: This version extends full compatibility to the latest Graviton4-based m8g instances, ensuring access to the newest generation of Arm performance on AWS. This builds on a strong history of Arm support in the stack, which began with experimental Arm instance compatibility in v5.1.0 and steadily expanded to include Graviton2 (c6gn) and later Graviton3 families (c7g, m7g, r7g) as well as other specialized Arm instance types like g5g, lm4gn, lm4gen, and x2gd in the previous versions.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/buildkite/elastic-ci-stack-for-aws/releases/tag/v5.1.0
    release_notes__recommended_minimum:
    other_info:

---
