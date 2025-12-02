---
name: Ceph
category: Storage
description: Ceph is an open-source, distributed storage system.
download_url: https://download.ceph.com/
works_on_arm: true
supported_minimum_version:
    version_number: 0.91
    release_date: 2015/01/14


optional_info:
    homepage_url: https://ceph.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.ceph.com/en/latest/cephadm/install/#install-cephadm
        arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/arm-demonstrates-leading-performance-on-ceph-storage-cluster
        partner_content:
    arm_recommended_minimum_version:
        version_number: Quincy 17.2.5
        release_date: 2023/02/22
        reference_content: https://amperecomputing.com/assets/Ampere_Arm_Processors_for_Ceph_WP_v1_00_20230222_1_fcd19200fb.pdf
        rationale: This content is focused on running Ceph on a multi-node cluster with Ampere Arm processors. The community version of Ceph (Quincy) was run on Ampere processors and no issues were discovered in the test cases attempted. Apart from delivering good performance, exceptional power savings while running Ceph is observed (the AMD node had a power consumption of approximately 350 watts, while the Ampere node consumed 225 watts).

optional_hidden_info:
    release_notes__supported_minimum: https://docs.ceph.com/en/latest/releases/hammer/#id35
    release_notes__recommended_minimum:
    other_info: The release notes for v0.91 says "aarch64 build fixes". However, there are dependency issues encountered while executing the install script on both ARM64 and AMD64 Ubuntu 18.04.

---

