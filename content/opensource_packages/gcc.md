---
name: GNU Toolchain (GCC)
category: Compilers/Tools
description: The GNU Compiler Collection (GCC) is a compiler system produced by the GNU Project supporting various programming languages.
download_url: https://gcc.gnu.org/releases.html
works_on_arm: true
supported_minimum_version:
  version_number: 6.5.0
  release_date: 2018/10/30
optional_info:
  homepage_url: https://gcc.gnu.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://gcc.gnu.org/onlinedocs/gcc/AArch64-Options.html
    arm_content: https://learn.arm.com/install-guides/gcc/native/
    partner_content:
      - display_name: Oracle OCI
        url: https://blogs.oracle.com/linux/post/building-aarch64-linux-kernel-ol8
  arm_recommended_minimum_version:
    version_number: 15
    release_date: 2025/08/08
    reference_content: https://gcc.gnu.org/gcc-15/changes.html
    rationale: In this release, GCC adds initial support for the Aarch64 MinGW target (C/C++) and introduces Armv9.5-A along with new CPUs (Apple M1–M3, Cortex-A725, Neoverse V3, NVIDIA Grace, etc.) and architectural features such as FP8, SME2.1 etc. The release also improves ACLE support, code generation (CRC, SVE/SME, FP8), and tuning, while refining options like -mbranch-protection and -mcpu=native.
optional_hidden_info:
  release_notes__supported_minimum: https://gcc.gnu.org/gcc-6/changes.html
  release_notes__recommended_minimum: null
  other_info: null
---
