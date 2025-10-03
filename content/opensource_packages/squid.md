---
name: Squid
category: Web Server
description: Squid is a caching proxy for the Web supporting HTTP, HTTPS, FTP, and more. It reduces bandwidth and improves response times by caching and reusing frequently-requested web pages.
download_url: https://github.com/squid-cache/squid/releases
works_on_arm: true
supported_minimum_version:
    version_number: 3.2.0.15
    release_date: 2012/02/05
 

optional_info:
    homepage_url: https://www.squid-cache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://wiki.squid-cache.org/SquidFaq/InstallingSquid
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.2.10
        release_date: 2024/12/30
        reference_content: https://github.com/squid-cache/squid/releases/tag/SQUID_3_2_10
        rationale: This version resolved an issue where ssl_crtd helper processes would crash during startup on ARM architectures.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done using released source code tar.

---
