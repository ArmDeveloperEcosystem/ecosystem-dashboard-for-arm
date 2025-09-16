---
name: MPFR
category: Miscellaneous
description: MPFR is a library designed for precise floating-point arithmetic, delivering accurate mathematical operations with support for arbitrary precision and a consistent interface for complex calculations.
download_url: https://www.mpfr.org/history.html
works_on_arm: true
supported_minimum_version:
    version_number: 3.1.1
    release_date: 2012/07/03


optional_info:
    homepage_url: https://www.mpfr.org
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://gitlab.inria.fr/mpfr/mpfr/-/blob/master/INSTALL?ref_type=heads
    arm_recommended_minimum_version:
        version_number: 4.2.2
        release_date: 2025/03/20
        reference_content: https://www.mpfr.org/mpfr-4.2.2/
        rationale: This version has been successfully built and validated on multiple Arm64 platforms, including Apple Darwin (clang 14.0.0), Linux (GCC 8.5.0 / 14.2.0, Clang 19.1.7 via Termux/Android, and tcc), as well as Linux-musl (GCC 14.2.0). This confirms stable Arm64 support across diverse toolchains and environments.

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the tar archive [3.1.1](https://www.mpfr.org/mpfr-3.1.1/). 

---
