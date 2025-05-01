---
name: Better Remote Procedure Call (BRPC)
category: Messaging/Comms
description: BRPC is a powerful framework for Remote Procedure Calls (RPC), tailored to enhance communication between distributed systems. It focuses on reducing delays and boosting data transfer speeds, making it ideal for handling inter-process interactions efficiently.
download_url: https://brpc.apache.org/docs/downloadbrpc/
works_on_arm: true
supported_minimum_version:
    version_number: 0.9.7
    release_date: 2020/03/06


optional_info:
    homepage_url: https://brpc.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://brpc.apache.org/docs/getting_started/
    arm_recommended_minimum_version:
        version_number: 1.4.0
        release_date: 2023/02/07
        reference_content: https://github.com/apache/brpc/releases/tag/1.4.0
        rationale: This version fixed "sched_to itself" error when building by Clang on Linux aarch64.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/apache/brpc/releases/tag/0.9.7
    release_notes__recommended_minimum:
    other_info:
  
---
