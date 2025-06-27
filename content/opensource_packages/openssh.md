---
name: OpenSSH
category: Networking
description: OpenSSH is a connectivity tool for remote SSH login, which encrypts all traffic to eliminate connection hijacking, eavesdropping, and other attacks.
download_url: https://www.openssh.com/ftp.html
works_on_arm: true
supported_minimum_version:
    version_number: V_8_2_P1
    release_date: 2020/02/14


optional_info:
    homepage_url: https://www.openssh.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/openssh/openssh-portable/tree/master#building-from-git
    arm_recommended_minimum_version:
        version_number: 9.9p2
        release_date: 2025/02/18
        reference_content: https://www.openssh.com/txt/release-9.9p2
        rationale: This release addresses two critical security vulnerabilities and several functional bugs in OpenSSH. It fixes CVE-2025-26465, a logic error in ssh(1) (versions 6.8p1–9.9p1) that could allow a man-in-the-middle (MITM) attacker to impersonate servers when the VerifyHostKeyDNS option is enabled. It also resolves CVE-2025-26466, a vulnerability in sshd(8) (versions 9.5p1–9.9p1) that could lead to CPU and memory denial-of-service via SSH2_MSG_PING packets, mitigated by the PerSourcePenalties setting. 

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes for Linux/ARM64. Version 8.2 P1 got built and successfully tested from source on Neoverse N1. Prior versions fail to build and test on both AMD64 and ARM64.

---
