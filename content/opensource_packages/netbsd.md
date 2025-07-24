---
name: NetBSD
category: Operating System
description: NetBSD is a fast, secure and free operating system similar to Unix, designed to run on a wide range of computers from large servers to smaller devices.
download_url: https://www.netbsd.org/releases/
works_on_arm: true
supported_minimum_version:
    version_number: 9.0
    release_date: 2020/02/14


optional_info:
    homepage_url: https://www.netbsd.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://www.netbsd.org/docs/guide/en/part-install.html
    arm_recommended_minimum_version:
        version_number: 10.0
        release_date: 2024/03/28
        reference_content: https://www.netbsd.org/releases/formal-10/NetBSD-10.0.html
        rationale: This version significantly improves performance and support for Arm/Aarch64 systems. The scheduler now better handles big.LITTLE cores, and Aarch64 I/O and networking performance has been greatly optimized. Cryptographic algorithms like AES and ChaCha now use CPU acceleration and constant-time execution for added security. Key Armv8-A features—PAN, PAC, and BTI—are now supported to strengthen memory safety and ROP protection. Linux binary compatibility is now available on Aarch64 via compat_linux(8). Virtualization support has been extended to VMware ESXi-Arm and Oracle Cloud. UEFI bootloader improvements and expanded device driver support further enhance the Arm user experience.


optional_hidden_info:
    release_notes__supported_minimum: https://www.netbsd.org/releases/formal-9/NetBSD-9.0.html
    release_notes__recommended_minimum:
    other_info:

---

