---
name: Libopus
category: Miscellaneous
description: Opus is a fully open, royalty-free audio codec designed for exceptional versatility across speech, music, and streaming. Standardized as IETF RFC 6716, it combines Skype’s SILK and Xiph.Org’s CELT technologies to deliver unmatched performance for real-time internet communication, storage, and broadcast applications.
download_url: https://opus-codec.org/downloads/
works_on_arm: true
supported_minimum_version:
    version_number: 0.9.9
    release_date: 2012/02/22


optional_info:
    homepage_url: https://opus-codec.org/
    support_caveats:
    alternative_options: 
    getting_started_resources:
        official_docs: https://github.com/xiph/opus/blob/main/README
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.5
        release_date: 2024/09/11
        reference_content: https://github.com/xiph/opus/releases/tag/v1.5
        rationale: This version marks a major leap with machine learning–driven enhancements in both encoder and decoder. It introduces Deep Redundancy (DRED) for significantly better packet loss robustness and Deep PLC for improved concealment. Low-bitrate speech quality is enhanced down to 6 kb/s wideband, while Neon (ARM) optimizations boost performance. The release also adds support for 4th and 5th order ambisonics, expanding its spatial audio capabilities.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum: 
    other_info: There are no release notes or binaries present for Linux/ARM64. Libopus version 0.9.7 is installed and tested on the Neoverse N1, using steps mentioned in [README.md](https://github.com/xiph/opus/blob/v0.9.7/README).

---
