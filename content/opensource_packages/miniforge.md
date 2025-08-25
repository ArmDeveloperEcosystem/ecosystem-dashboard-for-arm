---
name: Miniforge
category: Miscellaneous
description: Miniforge is a product of conda-forge. Miniforge is launched with a vision to provide Miniconda-like installers, with the added feature of conda-forge. Miniforge is the easiest way to get started with conda-forge.
download_url: https://conda-forge.org/miniforge/#latest-release
works_on_arm: true
supported_minimum_version:
  version_number: 4.8.2-0
  release_date: 2020/02/02
optional_info:
  homepage_url: https://github.com/conda-forge/miniforge
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/hpc/optimizing-compute-intensive-tasks-on-aws/
    official_docs: https://github.com/conda-forge/miniforge?tab=readme-ov-file#install
  arm_recommended_minimum_version:
    version_number: 23.3.1-0
    release_date: 2023/08/21
    reference_content: https://github.com/conda-forge/miniforge/releases/tag/23.3.1-0
    rationale: This release is the first to bundle conda-libmamba-solver and mamba with Miniforge, making it functionally identical to Mambaforge. The only distinction between the two is the default installation directory name. It includes conda 23.3.1, conda-libmamba-solver 23.3.0, and mamba 1.4.2, offering faster dependency resolution and improved performance.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: There are no Linux/ARM64 release notes. The first release of miniforge, i.e. 4.8.2-0, rolls out AArch64 installer. Kindly find it [here](https://conda-forge.org/miniforge/#4.8.2-0).
---
