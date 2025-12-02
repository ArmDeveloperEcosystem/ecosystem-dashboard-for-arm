---
name: Calico
category: Containers and Orchestration
description: Calico is an open-source project with an active development and user community. Calico Open Source has grown to be the most widely adopted solution for container networking and security.
download_url: https://github.com/projectcalico/calico/releases
works_on_arm: true
supported_minimum_version:
    version_number: 3.21.3
    release_date: 2022/01/13

optional_info:
    homepage_url: https://docs.tigera.io/calico/latest/about/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.tigera.io/calico/latest/getting-started/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.29.0
        release_date: 2024/10/28
        reference_content: https://github.com/projectcalico/calico/blob/release-v3.29/release-notes/v3.29.0-release-notes.md
        rationale: Calico now supports a tech-preview nftables dataplane, offering native Linux policy enforcement with enhanced kernel integration. Felix's route resync logic has been optimized, using 50% less CPU time and 80% less memory, significantly improving efficiency on Linux nodes. eBPF improvements include fixes for memory leaks, dual-stack compatibility, and enhanced ICMP and VXLAN traffic handling, improving network stability under load. Calico now sets Go’s GC threshold to 40%, reducing CPU usage, and exposes GOMAXPROCS for tuning CPU-bound performance.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/projectcalico/calico/releases/tag/v3.21.3
    release_notes__recommended_minimum:
    other_info: There are no release notes available for Linux/ARM64. The first binary release is rolled out in version 3.21.3.

---
