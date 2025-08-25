---
name: OpenSSL
category: Crypto
description: OpenSSL is a robust, full-featured open-source toolkit for TLS (formerly SSL), DTLS and QUIC (currently client side only) protocols.
download_url: https://www.openssl.org/source/
works_on_arm: true
supported_minimum_version:
  version_number: 1.0.2
  release_date: 2015/01/22
optional_info:
  homepage_url: https://www.openssl.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://developer.arm.com/Tools%20and%20Software/Security%20Library%20Projects
    partner_content:
      - display_name: Microsoft Azure
        url: https://techcommunity.microsoft.com/blog/linuxandopensourceblog/azure-linux-3-0-now-generally-available-with-azure-kubernetes-service-v1-32/4399804
    official_docs: https://wiki.openssl.org/index.php/Compilation_and_Installation
  arm_recommended_minimum_version:
    version_number: 3.3.0
    release_date: 2024/04/09
    reference_content: https://openssl-library.org/news/openssl-3.3-notes/
    rationale: Arm contributed optimizations for openSSl, latest being optimizations for AES-CTR for Neoverse V1 and V2.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: No arm64 specific release notes are available. However, on [official page](https://www.openssl.org/policies/general-supplemental/platforms.html) linux-aarch64 support is mentioned in seconadary platforms.Installation and testing was done through tar file.
---
