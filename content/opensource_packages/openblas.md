---
name: OpenBLAS
category: AI/ML
description: OpenBLAS is an open-source implementation of the BLAS and LAPACK APIs with many hand-crafted optimizations for specific processor types.
download_url: https://github.com/OpenMathLib/OpenBLAS/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.3.9
    release_date: 2020/03/02


optional_info:
    homepage_url: https://www.openblas.net/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/deep-learning-yitian-710
        partner_content:
        official_docs: https://github.com/OpenMathLib/OpenBLAS/wiki/Installation-Guide
    arm_recommended_minimum_version:
        version_number: 0.3.29
        release_date: 2025/01/12
        reference_content: https://github.com/OpenMathLib/OpenBLAS/releases/tag/v0.3.29
        rationale: This release fixes a critical bug in the generic c/zgemm_beta kernel that could cause out-of-bounds memory access. CPU autodetection was rewritten to scan all cores and select the highest-performing type, improving scheduling accuracy. DGEMM performance was enhanced for SVE targets, especially on small matrices, and SVE kernels were added for ROT and SWAP. Improvements were made to SGEMV and DGEMV SVE kernels on A64FX and Neoverse V1, along with better GEMM-to-GEMV routing logic. The build system now supports small matrix kernels in CMake, with better compile-time SVE detection and support for Apple M4, iOS, and NetBSD. Additional fixes include NRM2 corrections for Neoverse N2 and compatibility with the NVIDIA compiler on SVE targets.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/OpenMathLib/OpenBLAS/releases/tag/v0.3.9
    release_notes__recommended_minimum:
    other_info:

---
