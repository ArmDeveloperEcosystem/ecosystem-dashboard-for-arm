---
name: Gromacs
category: HPC
description: Free and open-source software suite for high-performance molecular dynamics and output analysis
download_url: https://manual.gromacs.org/current/download.html
works_on_arm: true
supported_minimum_version:
    version_number: 5.1
    release_date: 2015/12/31


optional_info:
    homepage_url: https://www.gromacs.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://manual.gromacs.org/current/install-guide/index.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2025.1
        release_date: 2025/03/11
        reference_content: https://manual.gromacs.org/2025.1/release-notes/2025/2025.1.html
        rationale:  This version corrects SIMD instruction guidance for Neoverse-V2 CPUs by recommending NEON over SVE where appropriate, ensuring better runtime performance. Compiler warnings related to Arm SVE have been silenced, resulting in a cleaner and more stable build experience.

optional_hidden_info:
    release_notes__supported_minimum: https://manual.gromacs.org/documentation/5.1/ReleaseNotes/index.html
    release_notes__recommended_minimum:
    other_info:

---
