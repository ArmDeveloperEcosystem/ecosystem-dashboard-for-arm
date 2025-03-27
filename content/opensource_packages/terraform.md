---
name: Terraform
category: DevOps
description: Terraform is an infrastructure as code tool. It is used to automate cloud infrastructure.
download_url: https://developer.hashicorp.com/terraform/install
works_on_arm: true
supported_minimum_version:
    version_number: 0.14.0
    release_date: 2020/12/01


optional_info:
    homepage_url: https://www.terraform.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/install-guides/terraform/
        partner_content: https://amperecomputing.com/tutorials/getting-started-on-azure-ampere-VMs-with-Debian-using-Terraform
        official_docs: https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum: https://releases.hashicorp.com/terraform/0.14.0/
    release_notes__recommended_minimum:
    other_info: Terraform's [official supported architectures](https://developer.hashicorp.com/terraform/cli/install/apt#supported-architectures) page still shows no support for arm64. They are releasing pre-compiled binary for arm64 as per the [issue](https://github.com/hashicorp/terraform/issues/14474). However, v0.14.0 is the official support for linux_arm64 as mentioned in the issue.
---
