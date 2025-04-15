---
name: Fmt
category: Languages and Frameworks
description: The fmt library is an open-source C++ formatting library that offers a fast and safe alternative to traditional formatting methods.
download_url: https://github.com/fmtlib/fmt/releases
works_on_arm: true
supported_minimum_version: 
    version_number: 0.8.0
    release_date: 2015/02/07


optional_info:
    homepage_url: https://fmt.dev/11.0/
    support_caveats:
    alternative_options: 
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://fmt.dev/11.0/get-started/#debianubuntu
    arm_recommended_minimum_version:
        version_number: 11.0.0
        release_date: 2024/07/01
        reference_content: https://github.com/fmtlib/fmt/releases/tag/11.0.0
        rationale: This version added fmt/base.h which provides a subset of the API with minimal include dependencies and enough functionality to replace all uses of the printf family of functions. This brings the compile time of code using {fmt} much closer to the equivalent printf code. This gives almost 4x improvement in build speed compared to version 10.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: There are no release notes or binaries present for Linux/ARM64. Fmt version 0.8.0 is installed and tested on the Neoverse N1, using steps mentioned [here](https://fmt.dev/11.0/get-started/#installation).

---
