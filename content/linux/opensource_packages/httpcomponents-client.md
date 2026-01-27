---
name: Apache Httpcomponents Client
category: Networking
description: Apache HttpComponents Client is a Java library designed to build HTTP clients. It streamlines making HTTP requests, processing responses, managing connections and supports protocols like HTTP/1.1, HTTP/2, and authentication mechanisms.
download_url: https://github.com/apache/httpcomponents-client/tags
works_on_arm: true
supported_minimum_version:
    version_number: rel/v5.2
    release_date: 2022/11/10


optional_info:
    homepage_url: https://hc.apache.org/httpcomponents-client-4.5.x/index.html
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/apache/httpcomponents-client/blob/master/BUILDING.txt
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 5.4
        release_date: 2024/09/19
        reference_content: https://github.com/apache/httpcomponents-client/blob/master/RELEASE_NOTES.txt
        rationale: This version introduced compatibility with Java Virtual Threads and Java 21 Runtime. Java virtual threads do the same work as traditional threads, but they’re managed by the JVM, not the OS. They work great for concurrent tasks (like handling many HTTP requests or database calls). If you’re running on multi-core CPUs like Arm-based servers (Graviton, Axion), Virtual Threads let you fully use all cores with lower overhead.

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done using tar archive [rel/v5.2](https://github.com/apache/httpcomponents-client/releases/tag/rel%2Fv5.2). 

---
