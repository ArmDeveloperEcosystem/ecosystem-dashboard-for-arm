---
name: gPerftools
category: Compilers/Tools
description: gPerftools is a collection of performance analysis tools designed to help developers optimize their applications.
download_url: https://github.com/gperftools/gperftools/releases
works_on_arm: true
supported_minimum_version: 
    version_number: 2.1.90
    release_date: 2015/08/16


optional_info:
    homepage_url: https://github.com/gperftools/gperftools
    support_caveats:
    alternative_options: 
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://github.com/gperftools/gperftools/blob/master/INSTALL
    arm_recommended_minimum_version:
        version_number: 2.10.80
        release_date: 2023/08/01
        reference_content: https://github.com/gperftools/gperftools/releases/tag/gperftools-2.10.80
        rationale: This release adds full support for Linux on AArch64 and RISC-V, including passing all unit tests. It deprecates the heap leak checker and fully transitions to C++11 std::atomic, removing legacy atomic code. Stacktrace support is improved with expanded generic_fp methods and better integration with glibc's dl_find_object API. Frame pointer handling is enhanced for better profiling, especially on Arm platforms with large page sizes. Dynamic page size detection improves memory management on 64K page Arm systems, with the option to override via an environment variable.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/gperftools/gperftools/releases/tag/gperftools-2.1.90
    release_notes__recommended_minimum: 
    other_info: 

---
