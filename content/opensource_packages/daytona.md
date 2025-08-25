---
name: Daytona
category: Containers and Orchestration
description: Daytona is an open source development environment manager. Set up a development environment on any infrastructure, local or remote, with a single command.
download_url: https://github.com/daytonaio/daytona/releases/
works_on_arm: true
supported_minimum_version:
  version_number: 0.11.0
  release_date: 2024/04/12
optional_info:
  homepage_url: https://www.daytona.io/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Daytona
        url: https://www.daytona.io/dotfiles/daytona-goes-open-source
    official_docs: https://github.com/daytonaio/daytona/blob/main/README.md
  arm_recommended_minimum_version:
    version_number: 0.21.0
    release_date: 2024/07/12
    reference_content: https://www.daytona.io/changelog/major-update-with-performance-boost
    rationale: From this version onwards, the workspace creation process now runs directly on the target machine (local or remote) instead of inside a container. This change results in a significant performance boost, especially for subsequent builds, as it leverages the host's Docker registry for caching.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: Daytona supports both x86 and ARM architectures, making it a great choice for development on Arm-based hardware.
---
