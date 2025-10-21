---
name: Docker CE
category: Containers and Orchestration
description: Docker CE (Community Edition) is an open-source platform for developing, shipping, and running applications in containers.
download_url: https://github.com/docker-archive/docker-ce/tags
works_on_arm: true
supported_minimum_version:
  version_number: 17.09.0
  release_date: 2017/09/27
optional_info:
  homepage_url: https://www.docker.com/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://www.docker.com/blog/getting-started-with-docker-for-arm-on-linux/
    arm_content: https://learn.arm.com/install-guides/docker/
    partner_content:
      - display_name: Alibaba Cloud
        url: https://www.alibabacloud.com/blog/arm-container-applications-accelerating-development-and-testing_595802
  arm_recommended_minimum_version:
    version_number: 24.0.3
    release_date: 2023/07/06
    reference_content: https://docs.docker.com/engine/release-notes/24.0/#2403
    rationale: This release significantly reduces CPU and memory usage when populating the debug section of GET/ info, improving performance during diagnostics. Packaging updates include Go 1.20.5, Docker Compose v2.19.1, and Buildx v0.11.1, ensuring runtime and build tool improvements.
optional_hidden_info:
  release_notes__supported_minimum: https://docs.docker.com/engine/release-notes/17.09/
  release_notes__recommended_minimum: null
  other_info: From the list available at [Docker's official download page](https://download.docker.com/linux/static/stable/aarch64/) for ARM64, it is clear that Docker CE 17.09.0 rolled out initial support for ARM64 architecture.
---
