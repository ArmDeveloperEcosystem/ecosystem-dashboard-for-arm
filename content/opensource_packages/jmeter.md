---
name: JMeter
category: Monitoring/Observability
description: JMeter is an open-source tool for load testing and web application performance, measuring their behavior under various conditions. It supports different protocols and simulates multiple users.
download_url: https://jmeter.apache.org/download_jmeter.cgi
works_on_arm: true
supported_minimum_version:
    version_number: 5.0
    release_date: 2018/09/18


optional_info:
    homepage_url: https://jmeter.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://jmeter.apache.org/usermanual/get-started.html#install
    arm_recommended_minimum_version:
        version_number: 5.5
        release_date: 2022/06/14
        reference_content: https://jmeter.apache.org/changes_history.html
        rationale: This version introduced support for Java 17 and added the new Open Model Thread Group, enabling dynamic, rate-based load profiles for more realistic simulations. It began transitioning from Oro to Java regex and incorporated Kotlin in core components for future extensibility. The release improved UI responsiveness, HTTP sampler capabilities, and support for protocols like Neo4j and GraphQL.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-5.0.zip).

---
