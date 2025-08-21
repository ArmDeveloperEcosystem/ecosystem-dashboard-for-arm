---
name: Smcpp
category: HPC
description: SMC++ is a statistical genetics tool designed to infer historical population size dynamics from whole-genome sequence data. It leverages coalescent modeling to provide scalable, high-resolution estimates of effective population size over time.
download_url: https://github.com/popgenmethods/smcpp/tags
works_on_arm: true
supported_minimum_version:
    version_number: 1.15.3
    release_date: 2019/11/18
 
 
optional_info:
    homepage_url: https://github.com/popgenmethods/smcpp
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/popgenmethods/smcpp#build-instructions
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no official release notes for Linux/ARM64 support. However, version 1.15.3 can be built on Arm via "pip install git+https://github.com/popgenmethods/smcpp@v1.15.3". Prior versions fail to build commonly on both Arm and x64 while dealing with use_2to3 dependency. GitHub releases do not roll out Arm artifacts.
 
---
