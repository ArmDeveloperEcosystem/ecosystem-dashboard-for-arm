---
name: 7-zip
category: Compression
description: 7-Zip is a file archiver known for its high compression ratio, supports various formats including ZIP, 7z, TAR, and RAR, and offers strong AES-256 encryption.
download_url: https://github.com/ip7z/7zip/releases
works_on_arm: true
supported_minimum_version:
  version_number: 22.00
  release_date: 2022/06/27
optional_info:
  homepage_url: https://www.7-zip.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
    official_docs: https://github.com/ip7z/7zip/tree/main/DOC#readme
  arm_recommended_minimum_version:
    version_number: 23.01
    release_date: 2023/12/17
    reference_content: https://github.com/ip7z/7zip/releases/tag/23.01
    rationale: This version adds a new ARM64 filter that improves compression ratio for ARM64 (AArch64) executables in 7z/xz formats. Executable files (.exe, .dll) are now parsed to apply the correct filter—BCJ/BCJ2 for x86, ARM64 for ARM64—instead of defaulting to x86 filters. The BCJ2 section size increased from 64 MiB to 240 MiB, improving compression for large binaries.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info:
---
