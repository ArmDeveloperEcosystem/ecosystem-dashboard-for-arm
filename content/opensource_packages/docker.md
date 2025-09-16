---
name: Docker
category: Containers and Orchestration
description: Docker is an open platform for developing, shipping, and running applications. Docker provides the ability to package and run an application in a loosely isolated environment called a container.
download_url: https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/arm64/
works_on_arm: true
supported_minimum_version:
  version_number: 1.11.0
  release_date: 2016/04/13
optional_info:
  homepage_url: https://www.docker.com/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://learn.arm.com/install-guides/docker/
    partner_content:
      - display_name: Alibaba Cloud
        url: https://www.alibabacloud.com/blog/arm-container-applications-accelerating-development-and-testing_595802
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/containers/how-to-build-your-containers-for-arm-and-save-with-graviton-and-spot-instances-on-amazon-ecs/
      - display_name: Microsoft Azure
        url: https://devblogs.microsoft.com/dotnet/improving-multiplatform-container-support/
      - display_name: Google GCP
        url: https://cloud.google.com/dataflow/docs/guides/multi-architecture-container
      - display_name: Oracle OCI
        url: https://blogs.oracle.com/linux/post/oracle-container-runtime-for-docker-on-oracle-linux-for-arm
    official_docs: https://www.docker.com/blog/getting-started-with-docker-for-arm-on-linux/
  arm_recommended_minimum_version:
    version_number: 24.0.3
    release_date: 2023/07/06
    reference_content: https://docs.docker.com/engine/release-notes/24.0/#2403
    rationale: This release significantly reduces CPU and memory usage when populating the debug section of GET/ info, improving performance during diagnostics. Packaging updates include Go 1.20.5, Docker Compose v2.19.1, and Buildx v0.11.1, ensuring runtime and build tool improvements.
optional_hidden_info:
  release_notes__supported_minimum: https://docs.docker.com/engine/release-notes/prior-releases/#misc
  release_notes__recommended_minimum: null
  other_info: Minimum Recommended Docker Version depends on the distros. For example, Jammy-20.10.13, Focal-19.03.10, Bionic-18.09.00
---
