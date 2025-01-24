---
name: Open-falcon
category: Monitoring/Observability
description: Open Falcon is a distributed and high-performance monitoring system. It's highly scalable, gives better performance with RRA(Round Robin Archive) mechanism, efficient, highly available, and flexible. It has a user-friendly dashboard, which can present multi-dimension graph.
download_url: https://github.com/open-falcon/falcon-plus/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.2.1
    release_date: 2017/08/15


optional_info:
    homepage_url: https://open-falcon.github.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/open-falcon/falcon-plus/blob/master/README.md#getting-started
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no Linux/ARM64 release notes. version 0.2.1 can be built from source on Neoverse N1 and open-falcon binary got generated, prior versions are failing to build on both AMD64 and ARM64. The docker images for open-falcon are not yet available for Linux/ARM64 in any version.

---
