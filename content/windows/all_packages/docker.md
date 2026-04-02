---
name: Docker
category: Containers and Orchestration
description: Docker is an open platform for developing, shipping, and running applications. Docker provides the ability to package and run an application in a loosely isolated environment called a container.
download_url: https://docs.docker.com/desktop/setup/install/windows-install/
works_on_arm: true
supported_minimum_version:
  version_number: 4.31
  release_date: 2024/05/23

optional_info:
  homepage_url: https://www.docker.com/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://docs.docker.com/
    arm_content: https://learn.arm.com/install-guides/docker/
    partner_content:
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
