---
name: Weather Research and Forecasting (WRF)
category: HPC
description: Weather Research and Forecasting (WRF) model is a numerical weather prediction (NWP) system designed for both atmospheric research and operational forecasting applications.
download_url: https://github.com/wrf-model/WRF/releases
works_on_arm: true
supported_minimum_version:
    version_number: v4.2.2
    release_date: 2021/01/15


optional_info:
    homepage_url: https://www.mmm.ucar.edu/models/wrf
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/high-performance-computing-blog/posts/bringing-wrf-up-to-speed-with-arm-neoverse
        partner_content: https://aws.amazon.com/blogs/hpc/numerical-weather-prediction-on-aws-graviton2/
        official_docs: https://www.mmm.ucar.edu/models/wrf/support
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: AArch64 support was added in the PR(https://github.com/wrf-model/WRF/pull/1301). The PR got merged in Dec 2020 and the next release after the merge is v4.2.2. Tested v4.2.2(https://github.com/wrf-model/WRF/releases/tag/v4.2.2) version and it works on AArch64.

---
