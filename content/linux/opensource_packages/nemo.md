---
name: Neural Modules (Nemo)
category: AI/ML
description: NVIDIA NeMo is a flexible AI framework designed for researchers and developers to build and fine-tune models in areas like language, speech, and vision.
download_url: https://github.com/NVIDIA/NeMo/releases
works_on_arm: true
supported_minimum_version:
    version_number: v1.0.0
    release_date: 2021/06/04

optional_info:
    homepage_url: https://www.nvidia.com/en-in/ai-data-science/products/nemo/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.nvidia.com/nemo-framework/user-guide/latest/getting-started.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.21.0
        release_date: 2023/10/26
        reference_content: https://github.com/NVIDIA/NeMo/releases/tag/v1.21.0
        rationale: This version removes nemo_text_processing as a requirement on ARM, since some scripts used to fail on ARM due to missing nemo_text_processing.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done manually using the released tar [file](https://github.com/NVIDIA/NeMo/releases/tag/v1.1.0).
 
---
