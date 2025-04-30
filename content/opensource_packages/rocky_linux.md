---
name: Rocky Linux
category: Operating System
description: Rocky Linux is a community-driven, enterprise-grade Linux distribution designed to be fully compatible with Red Hat Enterprise Linux (RHEL).
download_url: https://rockylinux.org/download
works_on_arm: true
supported_minimum_version:
    version_number: 8.4
    release_date: 2021/09/30


optional_info:
    homepage_url: https://rockylinux.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content: https://cloud.google.com/compute/docs/images/os-details#rocky_linux
        official_docs: https://docs.rockylinux.org/guides/virtualization/vbox-rocky/?h=arm64#prerequisites
    arm_recommended_minimum_version:
        version_number: 9.0
        release_date: 2022/07/14
        reference_content: https://rockylinux.org/news/rocky-linux-9-0-ga-release
        rationale: This version introduces GNOME 40 with a redesigned desktop experience, fractional scaling, and improved multi-display support. It adds performance-focused updates like XFS Direct Access (DAX) and the "eager write" option for NFS. Developers benefit from modern toolchains including GCC 11.2.1, LLVM 13.0.1, Rust 1.58.1, and Go 1.17.1, and updated language runtimes like Python 3.9, Node.js 16, Ruby 3.0.3, and PHP 8.0. Root SSH password login is disabled by default for enhanced security, and OpenSSL 3.0 brings FIPS-compliant improvements. System monitoring via the Cockpit web console is also enhanced.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Rocky Linux is separately releasing binaries for ARM64 platforms, ensuring full support for ARM64 architecture.

---

