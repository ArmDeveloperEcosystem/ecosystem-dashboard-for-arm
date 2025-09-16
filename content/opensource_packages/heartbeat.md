---
name: Heartbeat
category: Monitoring/Observability
description: Heartbeat, developed and maintained by Elastic, is a lightweight agent that monitors the availability of services and endpoints, providing uptime data and response time metrics for Elasticsearch observability.
download_url: https://www.elastic.co/downloads/past-releases#heartbeat
works_on_arm: true
supported_minimum_version:
    version_number: 7.12.0
    release_date: 2021/03/23


optional_info:
    homepage_url: https://www.elastic.co/guide/en/beats/libbeat/current/beats-reference.html
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://www.elastic.co/guide/en/beats/heartbeat/8.14/setup-repositories.html
    arm_recommended_minimum_version:
        version_number: 9.0.3
        release_date: 2025/06/24
        reference_content: https://www.elastic.co/docs/release-notes/beats#beats-9.0.3-fixes
        rationale: In this version, Elastic beats Linux/Arm64 build process was updated to use Debian 11 - matching the Linux/AMD64 build. Also, the statically linked glibc was upgraded from 2.28 to 2.31, improving compatibility and consistency across architectures. This fix is applicable to all beats.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/Arm64 release notes are not available. The first Linux/Arm64 tar is available in version [7.12.0](https://www.elastic.co/downloads/past-releases/heartbeat-7-12-0)

---
