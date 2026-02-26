---
name: Expat
category: Miscellaneous
description: Expat is a fast, stream-oriented XML parser library written in C. It efficiently parses XML data in a forward-only manner, making it ideal for embedded systems and high-performance applications.
download_url: https://github.com/libexpat/libexpat/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.1.0
    release_date: 2017/10/21


optional_info:
    homepage_url: https://libexpat.github.io
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/libexpat/libexpat#building-from-a-git-clone
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.6.2
        release_date: 2024/03/13
        reference_content: https://github.com/libexpat/libexpat/blob/R_2_6_2/expat/Changes
        rationale: This version resolved the security vulnerability, CVE-2024-28757, which prevented billion laugh attack with the isolated use of external parsers. The "Billion Laughs" attack is a denial-of-service attack targeting XML parsers, which can cause the parser to consume massive memory and CPU, ultimately crashing the application.

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done using tar archive [2.1.0](https://github.com/libexpat/libexpat/releases/tag/R_2_1_0). 

---
