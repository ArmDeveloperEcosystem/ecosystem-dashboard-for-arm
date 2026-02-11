---
name: OpenH264
category: Video
description: OpenH264 is an open-source video codec library developed by Cisco Systems that provides encoding and decoding of H.264 video streams.
download_url: https://github.com/cisco/openh264/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.0
    release_date: 2014/05/06


optional_info:
    homepage_url: https://www.openh264.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/cisco/openh264#for-all-platforms
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.5.0
        release_date: 2024/11/08
        reference_content: https://github.com/cisco/openh264/releases/tag/v2.5.0
        rationale: Version 2.1.1 already has rolled out arm and arm64 linux libraries. However, OpenH264 v2.5.0 brings a series of stability, performance, and compatibility improvements. It resolves several multi-threaded decoding issues and fixes a deadlock that could occur at the end of decoding, enhancing reliability in concurrent processing environments. Frame decode errors are also addressed, ensuring more accurate video playback. The release includes build system updates such as Meson build support for riscv64 and PAC/BTI (Pointer Authentication and Branch Target Identification) security enhancements. Additionally, it fixes cross-compilation from Darwin arm64 to x86_64 and resolves a specific decoding bug affecting H.264 streams encoded by Apple’s hardware encoder.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://github.com/cisco/openh264/releases/tag/v1.0).

---

