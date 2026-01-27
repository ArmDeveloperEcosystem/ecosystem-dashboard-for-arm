---
name: Dragonfly
category: Containers and Orchestration
description: Dragonfly is an open source P2P-based file distribution and image acceleration system.
download_url: https://github.com/dragonflyoss/Dragonfly2/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.0.5
    release_date: 2022/08/04


optional_info:
    homepage_url: https://d7y.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://d7y.io/docs/next/getting-started/quick-start/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.2.0
        release_date: 2024/12/31
        reference_content: https://github.com/dragonflyoss/dragonfly/releases/tag/v2.2.0
        rationale: The Dragonfly client, now written in Rust, ensures memory safety and improved performance while supporting features like bandwidth rate limiting for prefetch requests to optimize network utilization. It introduces leeching mode, efficient small I/O handling through Nydus integration, and a new V2 P2P protocol for better transfer performance. Enhanced Harbor integration enables multi-architecture image preheating with cluster-level granularity. Observability is improved through Prometheus and Grafana dashboards, while security is strengthened with mTLS support for gRPC and self-signed certificates. Additional updates include a redesigned management console, better documentation, and major bug fixes targeting thread safety, memory leaks, and system resilience. Dragonfly also extends support to AI model distribution via OCI spec and Git LFS acceleration.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: No ARM64 specific release notes are available. The first binary for ARM64 was released from v2.0.5 version. [Refer here](https://github.com/dragonflyoss/Dragonfly2/releases/tag/v2.0.5).

---

