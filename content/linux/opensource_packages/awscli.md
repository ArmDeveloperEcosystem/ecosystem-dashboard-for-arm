---
name: AWS CLI
category: DevOps
description: AWS CLI is a unified command-line interface for interacting with and managing Amazon Web Services.
download_url: https://pypi.org/project/awscli/#history
works_on_arm: true
supported_minimum_version:
    version_number: 1.20.30
    release_date: 2021/08/26
 
 
optional_info:
    homepage_url: https://aws.amazon.com/cli/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html
        arm_content: https://learn.arm.com/install-guides/aws-cli/
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.35.13
        release_date: 2024/10/24
        reference_content: https://github.com/aws/aws-cli/blob/35cee668c3f9b6e5470af6bf07af758dd5bf5b79/CHANGELOG.rst#L4586
        rationale: In this release, Amazon EC2 X8g, C8g and M8g instances are powered by AWS Graviton4 processors.
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/aws/aws-cli/blob/develop/CHANGELOG.rst
    release_notes__recommended_minimum:
    other_info: Version 1.20.30 added support for the AWS Graviton (AWS_ARM64) recommendation preference for Amazon EC2 instances.
 
---
