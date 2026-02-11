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
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://docs.cilium.io/en/stable/gettingstarted/k8s-install-default/#install-cilium
    arm_content:
    partner_content:
      - display_name: Oracle OCI
        url: https://docs.oracle.com/en/learn/oke-flannel-to-cilium-cni-plugin/index.html#introduction
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/cilium/cilium/releases/tag/v1.8.0
  release_notes__recommended_minimum: null
  other_info: In the [cilium documentation](https://docs.cilium.io/en/stable/gettingstarted/k8s-install-default/#install-cilium) it is mentioned that testing is done by using the cilium-cli tool. For cilium, 1.7.7 version supports arm64, but while testing we use cilium-cli release notes. The minimum version which supports the arm64 for cilium-cli is v0.1.
---
