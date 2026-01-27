---
name: GitLab
category: DevOps
description: Gitlab is a complete DevOps platform that enables developers to perform all the tasks in a project, from project planning and source code management to monitoring and security.
download_url: https://packages.gitlab.com/gitlab/gitlab-ee
works_on_arm: true
supported_minimum_version:
  version_number: 13.4.0
  release_date: 2020/09/22
optional_info:
  homepage_url: https://about.gitlab.com/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://about.gitlab.com/blog/2021/08/05/achieving-23-cost-savings-and-36-performance-gain-using-gitlab-and-gitlab-runner-on-arm-neoverse-based-aws-graviton2-processor/
    arm_content:
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/devops/unlock-the-power-of-ec2-graviton-with-gitlab-ci-cd-and-eks-runners/
      - display_name: Oracle OCI
        url: https://blogs.oracle.com/cloud-infrastructure/post/announcing-gitlab-arm-runner-support-for-the-arm-compute-platform-on-oracle-cloud-infrastructure
  arm_recommended_minimum_version:
    version_number: 18.2
    release_date: 2025/07/07
    reference_content: https://gitlab.com/gitlab-org/gitlab/-/releases/v18.2.0-ee
    rationale: In this version, container scanning introduces native support for Linux Arm64 container image variants. This removes the need for emulation when running on Arm64 runners, resulting in significantly faster analysis. Additionally, users can now scan multi-architecture images by setting the TRIVY_PLATFORM environment variable, improving both speed and compatibility for Software Composition Analysis workflows on Arm.
optional_hidden_info:
  release_notes__supported_minimum: https://gitlab.com/gitlab-org/gitlab/-/releases/v13.4.0-ee
  release_notes__recommended_minimum: null
  other_info: null
---
