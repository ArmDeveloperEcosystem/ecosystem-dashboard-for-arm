---
name: OpenDataPlane (ODP)
category: Networking
description: The ODP project defines APIs for portable high performance data plane applications. The APIs enable various implementation strategies without letting the application know about the implementation details.
download_url: https://opendataplane.org/index.php/services/download/
works_on_arm: true
supported_minimum_version:
    version_number: 1.28.0.0
    release_date: 2021/04/01


optional_info:
    homepage_url: https://opendataplane.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/cfs-file/__key/telligent-evolution-components-attachments/01-1996-00-00-00-00-62-45/ODP-White-Paper_5F00_Final.pdf
        partner_content:
        official_docs: https://opendataplane.org/index.php/services/get-started/
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/OpenDataPlane/odp/releases/tag/v1.28.0.0
    release_notes__recommended_minimum:
    other_info: New enumerations for ARMv8.7-A, ARMv9.0-A, ARMv9.1-A, and ARMv9.2-A ISA versions were added in version 1.28.0.0. However, version 1.36.0.0 is the minimum version that successfully got built and tested on the neoverse N1. Before version 1.36.0.0, the build fails on both Linux/ARM64 and Linux/AMD64 platforms because HMAC_CTX_free is deprecated since OpenSSL 3.0.

---
