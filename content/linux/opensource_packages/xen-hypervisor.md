---
name: Xen Project Hypervisor
category: Miscellaneous
description: Xen Project Hypervisor is an open-source, bare-metal hypervisor that runs multiple operating systems as virtual machines on one host.
download_url: https://xenproject.org/resources/downloads/
works_on_arm: true
supported_minimum_version:
    version_number: 4.4.0
    release_date: 2014/03/10

optional_info:
    homepage_url: https://xenproject.org/projects/hypervisor/
    support_caveats_inline: true
    support_caveats: "For [Xen 4.22 Arm64](https://xenbits.xen.org/docs/4.22-testing/SUPPORT.html#arm-v8) hardware and feature limits, see the [support matrix](https://xenbits.xen.org/docs/unstable/support-matrix.html).
        Supported features may have security exceptions; Experimental/Tech Preview features generally lack security support.
        This Arm-support claim excludes XAPI and XCP-ng."
    getting_started_resources:
        official_docs: https://wiki.xenproject.org/wiki/Xen_ARM_with_Virtualization_Extensions#Building_Xen_on_ARM

optional_hidden_info:
    release_notes__supported_minimum: https://xenproject.org/blog/xen-project-announces-the-4-4-release/
    other_info: "4.4.0: Arm64 hardware (X-Gene), stable guest ABI; historical minimum, not a deployment recommendation.
        4.3.0: experimental Arm support; AArch64 on models.
        No Arm performance recommendation or borrowed Xen CI test results."
---
