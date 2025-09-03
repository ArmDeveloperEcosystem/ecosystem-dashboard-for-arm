---
name: Opentelemetry-cpp
category: Monitoring/Observability
description: C++ Client for observability framework & toolkit designed to create, manage telemetry data such as traces, metrics, and log.
download_url: https://github.com/open-telemetry/opentelemetry-cpp/releases
works_on_arm: true
supported_minimum_version:
  version_number: 0.1.0
  release_date: 2020/12/18
optional_info:
  homepage_url: https://opentelemetry.io/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
    official_docs: https://opentelemetry.io/docs/languages/cpp/getting-started/
  arm_recommended_minimum_version:
    version_number: 1.18.0
    release_date: 2024/11/26
    reference_content: https://github.com/open-telemetry/opentelemetry-cpp/releases/tag/v1.18.0
    rationale: This version improves how opentelemetry-cpp handles yield() on Arm64/Aarch64 platforms. This improves the multi-threading capabilities.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: The Project don't build/test on Arm64 in ci although arm64 support is present, Refer- https://github.com/open-telemetry/opentelemetry-cpp/discussions/2261.
---
