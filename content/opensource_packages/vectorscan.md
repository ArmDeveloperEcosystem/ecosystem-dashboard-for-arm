---
name: Vectorscan
category: Networking
description: Hyperscan and by extension Vectorscan is a high-performance multiple regex matching library. It follows the regular expression syntax of the commonly-used libpcre library, but is a standalone library with its own C API.
download_url: https://github.com/VectorCamp/vectorscan/releases
works_on_arm: true
supported_minimum_version:
    version_number: 5.4.6
    release_date: 2022/01/21


optional_info:
    homepage_url: https://www.vectorcamp.gr/vectorscan/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/vectorscan/install/
        partner_content:
        official_docs:
    arm_recommended_minimum_version:
        version_number: 5.4.8
        release_date: 2022/09/13
        reference_content: https://github.com/VectorCamp/vectorscan/releases/tag/vectorscan%2F5.4.8
        rationale: This version delivers a notable performance boost on Arm, achieving 5–10% faster execution compared to version 5.4.7, and 10–20% gains on Power architectures. Key updates include NEON-based optimizations for Aarch64, improved shift/align primitives, use of efficient instructions like shrn, and various build and compatibility fixes such as improved CMake configuration and proper handling of PCRE downloads.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/VectorCamp/vectorscan/releases/tag/vectorscan%2F5.4.6
    release_notes__recommended_minimum:
    other_info: 

---
