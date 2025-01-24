---
name: Google Logging (glog)
category: Miscellaneous
description: Google Logging is a C++14 library that implements application-level logging, and it provides various helper macros and logging APIs based on C++-style streams.
download_url: https://github.com/google/glog/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.4.0
    release_date: 2019/03/22


optional_info:
    homepage_url: https://google.github.io/glog/stable/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://google.github.io/glog/stable/build/#cmake
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes specific to the Linux/ARM64 support, but the project can be built and tested from source using cmake, from version 0.4.0 onwards. before version 0.4.0, build fails on both AMD64 and ARM64 Linux platforms.

---
