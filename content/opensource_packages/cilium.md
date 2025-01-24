---
name: Cilium
category: Containers and Orchestration
description: Cilium is a networking, observability, and security solution with an eBPF-based dataplane.
download_url: https://github.com/cilium/cilium/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.8.0
    release_date: 2020/06/22


optional_info:
    homepage_url: https://cilium.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: 
        partner_content: https://docs.daocloud.io/en/network/modules/aliyun-terway/aliyun-cilium.html
        official_docs: https://docs.cilium.io/en/stable/gettingstarted/k8s-install-default/#install-cilium
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/cilium/cilium/releases/tag/v1.8.0
    release_notes__recommended_minimum:
    other_info: In the [cilium documentation](https://docs.cilium.io/en/stable/gettingstarted/k8s-install-default/#install-cilium) it is mentioned that testing is done by using the cilium-cli tool. For cilium, 1.7.7 version supports arm64, but while testing we use cilium-cli release notes. The minimum version which supports the arm64 for cilium-cli is v0.1.

---
