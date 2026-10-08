---
name: Xen Project Hypervisor
category: Miscellaneous
description: Xen Project Hypervisor is an open-source, bare-metal hypervisor that runs multiple operating systems as virtual machines on one host, distinct from Xen CI, the project's build and test automation.
download_url: https://xenproject.org/resources/downloads/
works_on_arm: true
supported_minimum_version:
    version_number: 4.4.0
    release_date: 2014/03/10

optional_info:
    homepage_url: https://xenproject.org/projects/hypervisor/
    support_caveats: |
        - **Historical support:** [Xen 4.4.0](https://xenproject.org/blog/xen-4-4-released/) established a stable Arm ABI, and upstream [confirmed Arm was no longer Tech Preview](https://lists.xenproject.org/archives/html/xen-devel/2014-03/msg00748.html). Earlier [Xen 4.3.0](https://xenproject.org/blog/xen-4-3-0-released/) introduced experimental Arm support, with AArch64 demonstrated on simulation models. These historical milestones are not recommendations to deploy obsolete releases.
        - **Release assessed:** [Xen 4.22](https://xenproject.org/blog/xen-4-22-release/), initially released on July 30, 2026, lists Xen on Armv8 in **AArch64 mode as supported**. The [4.22 support statement](https://xenbits.xen.org/docs/4.22-testing/SUPPORT.html#arm-v8) is the authority for this claim, not development-version documentation.
        - **Feature maturity:** In 4.22, AArch32 mode is Tech Preview and Armv8-R is Experimental. Host ACPI on Arm and EFI Secure Boot on Arm64 are Experimental. Under [Xen's status definitions](https://xenbits.xen.org/docs/4.22-testing/SUPPORT.html#definition-of-status-labels), Experimental and Tech Preview features are not security-supported; Supported includes security support unless explicitly qualified.
        - **Security exceptions:** Arm SMMUv1/SMMUv2 and non-PCI device passthrough are supported but not security-supported; SMMUv3 is Tech Preview. Architecture support does not guarantee support for every CPU revision or hardware configuration. Check the **4.22 column** and detailed caveats in the [versions and feature support matrix](https://xenbits.xen.org/docs/unstable/support-matrix.html).
        - **Documentation:** Use the [Xen 4.22 documentation](https://xenbits.xen.org/docs/4.22-testing/) and [4.22 build requirements](https://wiki.xenproject.org/wiki/Xen_Project_4.22_Release_Notes#Build_Requirements) alongside the Arm setup guide below. The guide contains historical examples; use the requirements and source tag for the release being installed.
        - **Separate projects:** This entry covers the upstream Xen Hypervisor, not Xen CI. It makes no Arm-support claim for XAPI or XCP-ng; separate assessments are tracked for [XAPI](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/issues/1100) and [XCP-ng](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/issues/1101).
    getting_started_resources:
        official_docs: https://wiki.xenproject.org/wiki/Xen_ARM_with_Virtualization_Extensions#Building_Xen_on_ARM

optional_hidden_info:
    release_notes__supported_minimum: https://xenproject.org/blog/xen-4-4-released/
    other_info: The supported minimum records the stable Arm ABI and exit from Tech Preview in 4.4.0, not the experimental 4.3.0 port. Release 4.22.0 is tagged RELEASE-4.22.0 at upstream commit d45d5687f1441495f4ee20d5e9940066c5fa5beb. No Arm performance recommendation or Xen CI smoke-test result is asserted for this entry.
---
