---
name: Network Mapper (Nmap)
category: Security applications
description: Nmap is a powerful network exploration utility that enables the detection of live hosts, open ports, and operational services within a network, making it an indispensable tool for network reconnaissance and vulnerability assessment.
download_url: https://nmap.org/download.html
works_on_arm: true
supported_minimum_version:
    version_number: 6.40
    release_date: 2013/07/28


optional_info:
    homepage_url: https://nmap.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/nmap/nmap?tab=readme-ov-file#installing
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 7.95
        release_date: 2024/04/23
        reference_content: https://nmap.org/changelog.html#7.95
        rationale: This version enhances Linux scanning accuracy with over 4,000 new OS fingerprints, including Linux 6.1 support, and improves service detection with 2,500+ updated signatures. It introduces profile-guided optimizations for faster port scanning and upgrades core libraries like libpcre2, zlib, Lua, and libssh2, enhancing performance and security. OS detection reliability is boosted with smarter retry mechanisms, making Nmap more robust on modern Linux environments. Additionally, several NSE scripts and bug fixes improve industrial protocol scanning and memory efficiency.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing were done using "apt-get install nmap". The minimum version of nmap 6.40 corresponds to ubuntu:14.04 and 7.80 to ubuntu:22.04.

---
