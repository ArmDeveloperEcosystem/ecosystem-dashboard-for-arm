---
name: Apache FreeMarker
category: Miscellaneous
description: Apache Freemarker is a class library for Java programmers. It's a generic tool to generate text output, anything from HTML to auto generated source code.
download_url: https://github.com/apache/freemarker/tags
works_on_arm: true
supported_minimum_version:
    version_number: 2.3.31
    release_date: 2021/02/16


optional_info:
    homepage_url: https://freemarker.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://freemarker.apache.org/docs/index.html
    arm_recommended_minimum_version:
        version_number: 2.3.33
        release_date: 2024/06/01
        reference_content: https://freemarker.apache.org/docs/versions_2_3_33.html
        rationale: This version optimized the string comparison using binary comparison over Unicode NFKC normalization, which improves template execution speed on all platforms. This isn't Arm-specific, but can benefit all Linux users on Arm.

optional_hidden_info:
    release_notes__supported_minimum: https://freemarker.apache.org/docs/versions_2_3_31.html
    release_notes__recommended_minimum:
    other_info:

---
