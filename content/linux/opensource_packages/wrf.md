---
name: Weather Research and Forecasting (WRF)
category: HPC
description: Weather Research and Forecasting (WRF) model is a numerical weather prediction (NWP) system designed for both atmospheric research and operational forecasting applications.
download_url: https://github.com/wrf-model/WRF/releases
works_on_arm: true
supported_minimum_version:
  version_number: 4.2.2
  release_date: 2021/01/15
optional_info:
  homepage_url: https://www.mmm.ucar.edu/models/wrf
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://www.mmm.ucar.edu/models/wrf/support
    arm_content: https://community.arm.com/arm-community-blogs/b/high-performance-computing-blog/posts/bringing-wrf-up-to-speed-with-arm-neoverse
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/hpc/numerical-weather-prediction-on-aws-graviton2/
  arm_recommended_minimum_version:
    version_number: 4.7.0
    release_date: 2025/04/25
    reference_content: https://github.com/wrf-model/WRF/releases/tag/v4.7.0
    rationale: This version introduces critical fix enabling successful DM (distributed memory) builds on AArch64 by correcting DMPARALLEL configuration in configure.defaults for both GCC and armclang.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: AArch64 support was added in the PR(https://github.com/wrf-model/WRF/pull/1301). The PR got merged in Dec 2020 and the next release after the merge is v4.2.2. Tested v4.2.2(https://github.com/wrf-model/WRF/releases/tag/v4.2.2) version and it works on AArch64.
---
