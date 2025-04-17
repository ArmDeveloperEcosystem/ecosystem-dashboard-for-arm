---
name: Akka
category: Runtimes
description: Akka by Lightbend is an open-source solution that provides a toolkit and runtime environment for creating scalable, fault-tolerant, and message-based applications that can handle high levels of concurrency and distribution, all while running on the Java Virtual Machine (JVM).
download_url: https://github.com/akka/akka/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.6.16
    release_date: 2021/08/26


optional_info:
    homepage_url: https://www.lightbend.com/akka
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://doc.akka.io/docs/akka/current/typed/guide/index.html
    arm_recommended_minimum_version:
        version_number: 2.8.0
        release_date: 2023/03/16
        reference_content: https://github.com/akka/akka/releases/tag/v2.8.0
        rationale: This version has introduced new features like API for dynamic scaling of Sharded daemon process instances, more fine grained control of stream error logging, included bug fixes and several performance optimisations in typed and streams actors.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing were done using released tar files.

---
