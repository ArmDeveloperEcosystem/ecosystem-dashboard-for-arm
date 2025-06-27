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
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/servers-and-cloud-computing-blog/posts/choosing-compilers-for-arm-hpc 
        partner_content: https://aws.amazon.com/blogs/hpc/best-practices-for-running-molecular-dynamics-simulations-on-aws-graviton3e/
        official_docs: https://docs.lammps.org/Build_make.html
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: There are no release notes for Linux/ARM64. First release on github, tagged as r13475, can be built on Linux/ARM64 with make. Executable binaries "lmp_serial" and "lmp_mpi" have been verified for Aarch64 using file command.

---
