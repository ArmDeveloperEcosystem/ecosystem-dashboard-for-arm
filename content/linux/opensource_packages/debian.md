---
name: Debian
category: Operating System
description: Debian is an operating system and a distribution of Free Software.
download_url: https://cdimage.debian.org/debian-cd/current/arm64/iso-cd/
works_on_arm: true
supported_minimum_version:
  version_number: 8
  release_date: 2018/06/23
optional_info:
  homepage_url: https://www.debian.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://www.debian.org/releases/stable/arm64/ch02s01.en.html#idm186
    arm_content: https://community.arm.com/oss-platforms/w/docs/501/debian
    partner_content:
      - display_name: Ampere
        url: https://amperecomputing.com/tutorials/getting-started-on-azure-ampere-VMs-with-Debian-using-Terraform
  arm_recommended_minimum_version:
    version_number: Debian 13 Trixie
    release_date: 2025/08/09
    reference_content: https://www.debian.org/News/2025/20250809
    rationale: This release integrates Linux kernel 6.12 LTS, GCC 14.2, and glibc 2.41, delivering improved stability and performance for Arm platforms. Optimized Arm64 cloud images are published for Amazon EC2, OpenStack, PlainVM, and GenericCloud, providing cloud-init integration and fast startup.
optional_hidden_info:
  release_notes__supported_minimum: https://www.debian.org/releases/jessie/arm64/release-notes.en.txt
  release_notes__recommended_minimum: null
  other_info: null
---
