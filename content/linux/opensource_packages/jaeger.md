---
name: Jaeger
category: Monitoring/Observability
description: Jaeger is a distributed tracing platform created by Uber Technologies and donated to Cloud Native Computing Foundation.
download_url: https://github.com/jaegertracing/jaeger/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.18.1
    release_date: 2020/06/19


optional_info:
    homepage_url: https://www.jaegertracing.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://www.jaegertracing.io/docs/1.54/getting-started/
        arm_content: https://community.arm.com/arm-research/b/articles/posts/an-approach-to-edge-compute-observability-and-performance-monitoring
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.0.0
        release_date: 2024/11/12
        reference_content: https://www.cncf.io/blog/2024/11/12/jaeger-v2-released-opentelemetry-in-the-core/
        rationale: This version introduced a new architecture that utilizes the OpenTelemetry Collector framework as its base, enhancing performance and scalability across all supported platforms.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/jaegertracing/jaeger/releases/tag/v1.18.1
    release_notes__recommended_minimum:
    other_info:

---
