---
name: Eigen
category: Languages and Frameworks
description: Eigen is a high-performance C++ library for linear algebra, offering a wide range of mathematical functionalities such as vectors, matrices and various numerical solvers.
download_url: https://gitlab.com/libeigen/eigen/-/releases
works_on_arm: true
supported_minimum_version:
    version_number: 3.2.10
    release_date: 2016/10/04


optional_info:
    homepage_url: https://eigen.tuxfamily.org/index.php?title=Main_Page
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://eigen.tuxfamily.org/dox/GettingStarted.html#title1
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Version 3.2.10 is tested successfully on both AArch64 and x86_64 platforms. In the previous versions "binder1st" and "binder2nd" are throwing warnings as these both are deprecated in C++11 as mentioned in [this bug](https://eigen.tuxfamily.org/bz/show_bug.cgi?id=1276).
---
