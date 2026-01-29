---
name: RabbitMQ
category: Messaging/Comms
description: RabbitMQ is an open-source, lightweight message broker. It acts as a central hub for applications to communicate asynchronously by sending and receiving messages.
download_url: https://github.com/rabbitmq/rabbitmq-server/releases
works_on_arm: true
supported_minimum_version:
    version_number: 3.0
    release_date: 2012/11/19


optional_info:
    homepage_url: https://rabbitmq.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://www.rabbitmq.com/documentation.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.11.0
        release_date: 2024/05/01
        reference_content: https://github.com/rabbitmq/rabbitmq-server/blob/main/release-notes/3.11.0.md
        rationale: RabbitMQ version 3.11.0 introduced significant performance enhancements for Arm-based architectures. This version requires Erlang 25.0 or later, which brings Just-In-Time (JIT) compilation and modern flame graph profiling tooling to both x86 and ARM64 CPUs. These features result in improved performance on ARM64 architectures.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info:	RabbitMQ is not architecture-specific and has common binaries released. Hence the minimum version is the first released version(3.0).
---
