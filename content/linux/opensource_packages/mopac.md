---
name: MOPAC (Molecular Orbital PACkage)
category: HPC
description: MOPAC (Molecular Orbital PACkage) is a computational chemistry tool for semi-empirical quantum calculations, enabling efficient modeling of molecular structures, reactions, and properties for both research and industrial use.
download_url: https://github.com/openmopac/mopac/tags
works_on_arm: true
supported_minimum_version:
    version_number: 22.0.4
    release_date: 2022/07/08


optional_info:
    homepage_url: http://openmopac.net/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/openmopac/mopac#cmake
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 23.0.0
        release_date: 2024/11/11
        reference_content: https://github.com/openmopac/mopac/releases/tag/v23.0.0
        rationale: In this iversion, Arm processor support was formalized by adopting OpenBLAS or vendor-provided BLAS libraries for Arm builds, delivering improved numerical performance compared to the x86-optimized Intel MKL previously used.

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Linux/Arm64 release notes are not available. Installation and testing are done using tar archive [22.0.4](https://github.com/openmopac/mopac/releases/tag/v22.0.4). 

---
