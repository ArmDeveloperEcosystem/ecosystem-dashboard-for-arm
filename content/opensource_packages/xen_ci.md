---
name: Xen CI
category: DevOps
description: Xen CI is a DevOps tool within the cloud-native ecosystem that automates the building, testing, and validation of the Xen Project's codebase.
download_url: https://github.com/xen-project/xen/tags
works_on_arm: true
supported_minimum_version:
    version_number: 4.3.0
    release_date: 2013/07/09


optional_info:
    homepage_url: https://xenproject.org/
    support_caveats:
    alternative_options: 
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://xenproject.org/developers/getting-started-devs/
    arm_recommended_minimum_version:
        version_number: 4.20.0
        release_date: 2025/03/05
        reference_content: https://github.com/xen-project/xen/blob/master/CHANGELOG.md#4200---2025-03-05
        rationale: This version introduces several improvements for Arm platforms, particularly enhancing FF-A (Firmware Framework for Arm) support by adding indirect message handling, RXTX buffer transmission to the SPMC, and fixes for version negotiation and partition info retrieval. Experimental support for Armv8-R architecture has been added, along with support for the NXP S32G3 processor family and the LINFlexD UART driver. Additionally, SCMI requests over SMC using Shared Memory can now be forwarded to EL3 firmware when originating from hardware domains. The update also enables CONFIG_UBSAN in GitLab CI for Arm64 and other architectures, and introduces support for LLC (Last Level Cache) coloring to improve cache partitioning control on supported hardware.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/xen-project/xen/tree/RELEASE-4.3.0
    release_notes__recommended_minimum:
    other_info: ARM64 support is first announced in the [Readme.md](https://github.com/xen-project/xen/blob/RELEASE-4.3.0/README) in version 4.3.0.

---
