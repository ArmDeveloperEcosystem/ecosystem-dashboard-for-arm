---
name: Dav1d
category: Video
description: Dav1d is an AV1 cross-platform decoder, open-source, and focused on speed and correctness.
download_url: https://github.com/videolan/dav1d/tags
works_on_arm: true
supported_minimum_version:
    version_number: 0.1.0
    release_date: 2018/12/11


optional_info:
    homepage_url: https://code.videolan.org/videolan/dav1d/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/videolan/dav1d/blob/master/README.md
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.5.1
        release_date: 2025/01/20
        reference_content: https://github.com/videolan/dav1d/blob/master/NEWS
        rationale: This version delivers performance and stability improvements with a focus on stack reduction and Arm optimizations. The loop restoration filters (SGR and Wiener) have been rewritten to significantly lower stack usage, reducing it to 58 KB on Arm and Aarch64. Key enhancements include improved loop restoration performance on Arm32 and Arm64, a new NEON-based implementation of load_tmvs for Aarch64, and overall efficiency gains. Additionally, the release addresses a rare potential deadlock issue in flush() to improve stability.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes or binaries present for Linux/ARM64. Version 0.1.0 is installed and tested on the Neoverse N1, using steps mentioned in [README.md file](https://github.com/videolan/dav1d/blob/master/README.md).

---
