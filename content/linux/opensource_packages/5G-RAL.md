---
name: 5G RAL (RAN Acceleration library)
category: Networking
description: Arm RAN Acceleration library (ArmRAL) implements common signal processing functions in 5G Radio Access Network using Arm Neoverse cores.
download_url: https://git.gitlab.arm.com/networking/ral/-/releases
works_on_arm: true
supported_minimum_version:
    version_number: 20.10
    release_date: 2020/10/02


optional_info:
    homepage_url: https://developer.arm.com/documentation/102249/2410/Tutorials/Get-started-with-Arm-RAN-Acceleration-Library?lang=en
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://developer.arm.com/documentation/102249/2410/Tutorials/Use-Arm-RAN-Acceleration-Library?lang=en
        arm_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/introducing-arm-ran-acceleration-library
        partner_content:
    arm_recommended_minimum_version:
        version_number: 24.1
        release_date: 2024/10/07
        reference_content: https://gitlab.arm.com/networking/ral/-/releases/armral-24.10
        rationale: In this release, armral_turbo_perm_idx_init was added for LTE Turbo permutation indices, and armral_turbo_decode_block/_noalloc was updated to optionally use a user-allocated buffer for improved performance. armral_cmplx_matmul_i16_noalloc was introduced for complex matrix multiplication without memory allocation. FFT routines armral_fft_execute_cf32 and _cs16 now use Bluestein's algorithm for faster computation in previously recursive cases.

optional_hidden_info:
    release_notes__supported_minimum: https://developer.arm.com/documentation/102249/2410?lang=en
    release_notes__recommended_minimum:
    other_info:

---
