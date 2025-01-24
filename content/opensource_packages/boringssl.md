---
name: BoringSSL
category: Crypto
description: BoringSSL is a custom version of OpenSSL that was created and maintained by Google.
download_url: https://github.com/google/boringssl/tags
works_on_arm: true
supported_minimum_version:
    version_number: fips-20220613
    release_date: 2022/12/07


optional_info:
    homepage_url: https://boringssl.googlesource.com/boringssl
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/google/boringssl/blob/fips-20220613/BUILDING.md#building
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Release notes for Linux/ARM64 are not available. Downloaded the tar from Git and built on Neoverse N1 as part of testing. Only the latest version (currently fips-20220613) gets built, following the steps for building mentioned [here](https://github.com/google/boringssl/blob/fips-20220613/BUILDING.md#building).

---
