---
name: QEMU
category: Compilers/Tools
description: QEMU is an open-source emulator that allows developers to run ARM-based systems on a non-ARM host, providing a complete system emulation.
download_url: https://download.qemu.org/
works_on_arm: true
supported_minimum_version:
    version_number: 1.6.0
    release_date: 2013/08/15


optional_info:
    homepage_url:
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://www.qemu.org/download/#linux
        arm_content: https://community.arm.com/oss-platforms/w/docs/510/spawn-a-linux-virtual-machine-on-arm-using-qemu-kvm
        partner_content:
    arm_recommended_minimum_version:
        version_number: 8.2.0
        release_date: 2023/12/20
        reference_content: https://www.qemu.org/2023/12/20/qemu-8-2-0/
        rationale: In this version, architectural feature support for PACQARMA3, EPAC, Pauth2, FPAC, FPACCOMBINE, TIDCP1, MOPS, HBC, and HPMN0 have been added for ARM. This version also includes CPU emulation support for cortex-a710 and neoverse-n2.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing were done using released tar files.

---
