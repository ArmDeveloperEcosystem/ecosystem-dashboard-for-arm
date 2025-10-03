---
name: Snort
category: Security applications
description: Snort is an open-source and lightweight network intrusion detection system (NIDS) software for Linux and Windows to detect emerging threats.
download_url: https://www.snort.org/downloads
works_on_arm: true
supported_minimum_version:
    version_number: 2.9.15.1
    release_date: 2020/01/06


optional_info:
    homepage_url: https://www.snort.org/
    support_caveats:
    alternative_options: 
    getting_started_resources:
        official_docs: https://docs.snort.org/start/
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/vectorscan/snort/
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.1.77.0
        release_date: 2023/12/22
        reference_content: https://github.com/snort3/snort3/releases/tag/3.1.77.0
        rationale: This versions officially adds the arm compilation support to the build process.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Although snort2 is no longer supported, the minimum version installed through apt-get is 2.9.15.
---
