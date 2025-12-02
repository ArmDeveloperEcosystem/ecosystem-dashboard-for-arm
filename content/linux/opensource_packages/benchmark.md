---
name: Benchmark
category: Miscellaneous
description: Benchmark is a library to benchmark code snippets, similar to unit tests.
download_url: https://github.com/google/benchmark/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.7.1
    release_date: 2022/11/11


optional_info:
    homepage_url: https://github.com/google/benchmark
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/google/benchmark?tab=readme-ov-file#installation
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.9.2
        release_date: 2025/03/25
        reference_content: https://github.com/google/benchmark/releases/tag/v1.9.2
        rationale: This release brings major build system and CI improvements, including ARM build-and-test support on GitHub Actions and enhanced compatibility across Linux platforms. It introduces better CPU detection logic using sysconf() and removes deprecated /proc/cpuinfo usage with a fallback for specific systems. Several clang-tidy cleanups and modernization changes like unique_ptr usage and removal of outdated C++03 tests improve code quality. Also included are bug fixes for Hexagon, memory management, and build issues, along with updates to dependencies like gtest and nanobind.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/google/benchmark/releases/tag/v1.7.1
    release_notes__recommended_minimum:
    other_info:

---
