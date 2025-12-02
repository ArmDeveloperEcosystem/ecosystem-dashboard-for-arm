---
name: Valgrind
category: Monitoring/Observability
description: Valgrind is an instrumentation framework for building dynamic analysis tools. It aids in detecting memory management and threading bugs in applications.
download_url: https://valgrind.org/downloads/current.html
works_on_arm: true
supported_minimum_version:
    version_number: 3.10.0
    release_date: 2014/09/11

optional_info:
    homepage_url: https://valgrind.org/
    support_caveats: Certain Valgrind tools may have limitations on Arm servers.
    alternative_options:
    getting_started_resources:
        official_docs: https://valgrind.org/docs/manual/manual.html
        arm_content: https://community.arm.com/arm-community-blogs/b/architectures-and-processors-blog/posts/valgrind-3-10-0-supports-64-bit-armv8
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.23.0
        release_date: 2024/04/26
        reference_content: https://valgrind.org/docs/manual/dist.news.html
        rationale: In this version, support for FreeBSD and dotprod instructions (sdot/udot) were added for Arm64.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Released proper Arm64 support in version 3.10.0.
---
