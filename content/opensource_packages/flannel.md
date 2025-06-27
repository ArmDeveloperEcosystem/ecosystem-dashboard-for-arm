---
name: Flannel
category: Containers and Orchestration
description: Flannel is a networking tool used to construct a layer 3 network for Kubernetes clusters. Its primary function is to assign IP addresses to pods and facilitate traffic routing among them.
download_url: https://github.com/flannel-io/flannel/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.7.1
    release_date: 2017/04/19


optional_info:
    homepage_url: https://github.com/flannel-io/flannel
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/flannel-io/flannel/blob/master/Documentation/building.md
    arm_recommended_minimum_version:
        version_number: 0.19.1
        release_date: 2022/08/05
        reference_content: https://github.com/flannel-io/flannel/releases/tag/v0.19.1
        rationale: This version bumps etcd version to 3.5.1, that lets the functional tests pass successfully on Linux/ARM64 platform.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/flannel-io/flannel/releases/tag/v0.7.1
    release_notes__recommended_minimum: 
    other_info:

---
