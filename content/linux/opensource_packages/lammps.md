---
name: LAMMPS (Large-scale Atomic/Molecular Massively Parallel Simulator)
category: HPC
description: LAMMPS is a classical molecular dynamics code optimized for parallel computing, used primarily for simulating materials at the atomic scale.
download_url: https://www.lammps.org/download.html
works_on_arm: true
supported_minimum_version:
  version_number: r13475
  release_date: 2015/08/15
optional_info:
  homepage_url: https://www.lammps.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://docs.lammps.org/Build_make.html
    arm_content: https://community.arm.com/arm-community-blogs/b/servers-and-cloud-computing-blog/posts/choosing-compilers-for-arm-hpc
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/hpc/best-practices-for-running-molecular-dynamics-simulations-on-aws-graviton3e/
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: There are no release notes for Linux/ARM64. First release on github, tagged as r13475, can be built on Linux/ARM64 with make. Executable binaries "lmp_serial" and "lmp_mpi" have been verified for Aarch64 using file command.
---
