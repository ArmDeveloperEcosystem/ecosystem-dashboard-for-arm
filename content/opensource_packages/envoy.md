---
name: Envoy
category: Containers and Orchestration
description: Envoy is an open-source, high-performance proxy service. It is designed to be a scalable, flexible, and low-latency service proxy, particularly well-suited for microservice architectures and containerized applications.
download_url: https://github.com/envoyproxy/envoy/releases
works_on_arm: true
supported_minimum_version:
  version_number: v1.16.0
  release_date: 2020/10/08
optional_info:
  homepage_url: https://github.com/envoyproxy/envoy
  support_caveats: Istio support for aarch64 was added in [v1.15](https://istio.io/latest/news/releases/1.15.x/announcing-1.15/change-notes/) (Aug-31-2022). Istio and Envoy are often used together.
  alternative_options: null
  getting_started_resources:
    arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/envoy/
    partner_content:
    official_docs: https://www.envoyproxy.io/docs/envoy/latest/start/install#install-envoy-on-ubuntu
  arm_recommended_minimum_version:
    version_number: 1.30.0
    release_date: 2024/04/16
    reference_content: https://www.envoyproxy.io/docs/envoy/latest/version_history/v1.30/v1.30.0
    rationale: Envoy v1.30.0 introduced a configuration change where the envoy.restart_features.use_fast_protobuf_hash feature was enabled by default. This adjustment is expected to enhance the performance of hash operations by 2x to 10x and reduce configuration update times by 10-25%. While these improvements are general and not exclusive to any specific architecture, they may positively impact performance on Arm-based systems.
optional_hidden_info:
  release_notes__supported_minimum: https://www.envoyproxy.io/docs/envoy/v1.16.0/version_history/current#new-features
  release_notes__recommended_minimum: null
  other_info: null
---
