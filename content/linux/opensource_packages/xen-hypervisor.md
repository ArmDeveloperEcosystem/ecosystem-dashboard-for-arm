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
    support_caveats: >-
        The 4.4.0 minimum records historical AArch64 hardware support, not a production-version recommendation.
        [Xen 4.22 supports Armv8 AArch64](https://xenbits.xen.org/docs/4.22-testing/SUPPORT.html#arm-v8), with hardware and feature limitations listed in the **4.22 column** of the [support matrix](https://xenbits.xen.org/docs/unstable/support-matrix.html).
        Unless otherwise documented, Supported features include security support; Experimental and Tech Preview features do not.
        Arm SMMUv1/SMMUv2 and non-PCI device passthrough are supported but not security-supported.
        This entry covers Xen Hypervisor, not Xen CI, and makes no Arm-support claim for XAPI or XCP-ng, which require separate assessment.
    getting_started_resources:
        official_docs: https://wiki.xenproject.org/wiki/Xen_ARM_with_Virtualization_Extensions#Building_Xen_on_ARM

optional_hidden_info:
    release_notes__supported_minimum: https://xenproject.org/blog/xen-project-announces-the-4-4-release/
    other_info: >-
        The historical minimum records Xen 4.4.0's documented AArch64 hardware support, including AppliedMicro X-Gene, and its stable Arm guest ABI.
        Xen 4.3.0 introduced experimental Arm support; its release announcement describes AArch64 operation on models.
        This is a hardware/ABI milestone, not a production recommendation or security-support claim for 4.4.0.
        Release 4.22.0 is tagged RELEASE-4.22.0 at upstream commit d45d5687f1441495f4ee20d5e9940066c5fa5beb.
        No Arm performance recommendation or Xen CI smoke-test result is asserted for this entry.
---
