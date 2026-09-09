---
name: Albumentations
category: AI/ML
description: Albumentations is an open-source image augmentation library that helps improve computer vision models by efficiently applying rich, flexible transformations during training.
download_url: https://pypi.org/project/albumentations/#history
works_on_arm: true
supported_minimum_version:
    version_number: 0.0.2
    release_date: 2018/06/28
 
 
optional_info:
    homepage_url: https://albumentations.ai/
    support_caveats: "For the historical 0.0.2 minimum, use NumPy 1.x and opencv-python earlier than 4.12. Its imgaug 0.4.0 dependency calls NumPy APIs removed in NumPy 2, while opencv-python 4.12 and later require NumPy 2 on current Python."
    alternative_options:
    getting_started_resources:
        official_docs: https://albumentations.ai/docs/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: The release notes for the initial Linux/Arm64 support are not available. Albumentations 0.0.2 can be installed on Arm64 with pip and Python 3.7. The native smoke workflow also exercises a real image transform on Python 3.12 with the compatibility constraints listed above.
 
---
