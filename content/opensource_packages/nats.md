---
name: NATS
category: Messaging/Comms
description: NATS is a simple, secure and performant communications system for digital systems, services and devices.
download_url: https://nats.io/download/
works_on_arm: true
supported_minimum_version:
    version_number: 1.0.4
    release_date: 2018/02/21


optional_info:
    homepage_url: https://nats.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://docs.nats.io/running-a-nats-service/introduction/installation
    arm_recommended_minimum_version:
        version_number: 2.11
        release_date: 2025/03/20
        reference_content: https://nats.io/blog/nats-server-2.11-release/#whats-new-in-211
        rationale: This version brings several important features requested by the community, introduced the Multi Message Get feature, enabling batch retrieval of messages. This enhancement offers a more efficient approach to processing streams without the overhead of creating dedicated consumers or fetching messages individually.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/nats-io/nats-server/releases/tag/v1.0.4
    release_notes__recommended_minimum:
    other_info:

---
