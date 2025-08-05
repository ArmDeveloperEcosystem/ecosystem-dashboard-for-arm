---
name: SUSE
category: Operating System
description: SUSE Linux Enterprise Server (SLES) is a Linux-based server operating system designed for mainframes, servers, workstations and desktop computers.
download_url: https://www.suse.com/download/sles/
works_on_arm: true
supported_minimum_version:
    version_number: 12 SP2
    release_date: 2016/11/08


optional_info:
    homepage_url: https://www.suse.com/
    support_caveats: There are minimum hardware requirements to install SUSE on Arm hardware. For all details, read [this install guide from SUSE.](https://documentation.suse.com/sles/15-SP1/html/SLES-all/cha-aarch64.html) 
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://documentation.suse.com/sles/15-SP5/
    arm_recommended_minimum_version:
        version_number: 15 SP5
        release_date: 2025/07/18
        reference_content: https://www.suse.com/c/simple-vm-management-on-ampere-infrastructure/
        rationale: SUSE Virtualization 1.5 brings full GA support for VM management on Arm64-based Kubernetes clusters running on Ampere infrastructure. With SLES 15 SP5 as the underlying OS, users gain not only compatibility but also efficiency—thanks to its support for 64K kernel page sizes. This combination provides a high-performance foundation for virtualization on Arm64, making SUSE Virtualization 1.5 both production-ready and cloud-native friendly.

optional_hidden_info:
    release_notes__supported_minimum:  https://www.suse.com/releasenotes/aarch64/SUSE-SLES/12-SP2/index.html
    release_notes__recommended_minimum:
    other_info: 

---
