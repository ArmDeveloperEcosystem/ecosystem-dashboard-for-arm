---
name: Phoronix Test Suite
category: Monitoring/Observability
description: The Phoronix Test Suite is a free benchmarking tool for Linux that enables users to execute various performance tests, analyze the results, and compare performance metrics across different systems.
download_url: https://github.com/phoronix-test-suite/phoronix-test-suite/releases
works_on_arm: true
supported_minimum_version:
    version_number: 7.8.0
    release_date: 2018/02/18


optional_info:
    homepage_url: https://www.phoronix-test-suite.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://github.com/phoronix-test-suite/phoronix-test-suite#installation--setup
    arm_recommended_minimum_version:
        version_number: 10.8.2
        release_date: 2022/02/13
        reference_content: https://github.com/phoronix-test-suite/phoronix-test-suite/releases/tag/v10.8.2
        rationale: This version is a minor point release focused on input sanitization improvements for Phoromatic Server and overall system stability. It adds virtual test suites for “aarch64” and “riscv”, streamlining test discovery for 64-bit Arm and RISC-V platforms. Support has been extended for Arm Cortex-X1C detection and temperature reporting on additional SoCs, including the Raspberry Pi 400. Compatibility enhancements for Arch Linux and RHEL7 (PHP 5.4) are also included, along with internal test suite refactoring to improve automation and scalability.

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the tar archive [7.8.0](https://github.com/phoronix-test-suite/phoronix-test-suite/releases/tag/v7.8.0). 

---
