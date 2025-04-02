---
name: Libuv
category: Runtimes
description: Libuv is a cross-platform library designed for asynchronous I/O operations.
download_url: https://github.com/libuv/libuv/tags
works_on_arm: true
supported_minimum_version:
    version_number: v1.15.0
    release_date: 2017/10/03

optional_info:
    homepage_url: https://libuv.org/
    support_caveats:
    alternative_options: 
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://github.com/libuv/libuv/blob/v1.x/README.md
    arm_recommended_minimum_version:
        version_number: 1.45.0
        release_date: 2023/05/19
        reference_content: https://github.com/libuv/libuv/releases/tag/v1.45.0
        rationale: Version 1.45.0 introduced support for IO_uring, which significantly enhances asynchronous file operations on Linux systems. Performance improvements of up to 8x have been observed with IO_uring integration. Kindly refer [here](https://github.com/libuv/libuv/pull/3952). While these enhancements are not exclusive to Arm architectures, Arm-based systems running on compatible Linux kernels can benefit from these general performance improvements.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: There are no release notes or binaries present for Linux/ARM64. Libuv version 1.15.0 is installed and tested on the Neoverse N1, using steps mentioned in [README.md](https://github.com/libuv/libuv/tree/v1.15.0).

---
