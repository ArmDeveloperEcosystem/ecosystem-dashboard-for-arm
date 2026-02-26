---
name: Haproxy
category: Web Server
description: Haproxy provides a high availability load balancer and Proxy for TCP and HTTP-based applications that spreads requests across multiple servers.
download_url: https://www.haproxy.org/#down
works_on_arm: true
supported_minimum_version:
    version_number: 1.5.0
    release_date: 2014/06/19


optional_info:
    homepage_url: https://www.haproxy.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://www.haproxy.com/blog/haproxy-forwards-over-2-million-http-requests-per-second-on-a-single-aws-arm-instance
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Haproxy can be built successfully on ARM64 from version 1.4 onwards, but this version was released on Feb 26, 2010 (before the release of AArch64). The next AArch64-supported Haproxy version is 1.5.0.

---
