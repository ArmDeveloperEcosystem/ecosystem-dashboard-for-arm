---
name: OpenEmbedded (Yocto)
category: Languages and Frameworks
description: Openembedded-yocto project is a framework that assists in crafting custom linux distributions for embedded systems with a modular approach and cross-compilation support bolstered by a vibrant community for versatile hardware adaptability and efficient development.
download_url: https://git.openembedded.org/openembedded-core
works_on_arm: true
supported_minimum_version:
  version_number: v4.0 (kirkstone)
  release_date: 2022/04/01
optional_info:
  homepage_url: https://www.openembedded.org/wiki/OpenEmbedded-Core
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://learn.arm.com/learning-paths/embedded-systems/yocto_qemu/yocto_build/
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/industries/building-an-automotive-embedded-linux-image-for-edge-using-arm-graviton-yocto-project-soafee/
    official_docs: https://docs.yoctoproject.org/brief-yoctoprojectqs/index.html
  arm_recommended_minimum_version:
    version_number: v5.0 (scarthgap)
    release_date: 2024/04/01
    reference_content: https://docs.yoctoproject.org/migration-guides/release-notes-5.0.html#new-features-enhancements-in-5-0
    rationale: In this release, the new genericarm64 MACHINE was introduced to represent a 64-bit Arm SystemReady platform. For Armv9, redundant CRC/SVE tunes were dropped (now defaults in GCC), and new Arm tunes from GCC 13.2.0 were added. The default kernel was updated to 6.6 LTS, with support for genericarm64.
optional_hidden_info:
  release_notes__supported_minimum: https://docs.yoctoproject.org/migration-guides/release-notes-4.0.html
  release_notes__recommended_minimum: null
  other_info: null
---
