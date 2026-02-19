---
name: Ampere Optimized TensorFlow
category: AI/ML
description: Ampere Optimized TensorFlow is an inference acceleration backend that improves TensorFlow performance on Ampere Altra ARM CPUs using optimized compute kernels and multi-threading, enabling faster execution without requiring changes to existing TensorFlow models.
download_url: https://hub.docker.com/r/amperecomputingai/tensorflow/tags
works_on_arm: true
supported_minimum_version:
    version_number: 1.4.0
    release_date: 2022/12/01
 
 
optional_info:
    homepage_url: https://amperecomputing.com/developers/power-your-ai
    support_caveats: Ampere Optimized TensorFlow targets the Ampere Altra family of Arm64 processors. While Arm64 compatibility may predate 1.4.0, official packaged distributions (Docker images) are available starting from version 1.4.0.
    alternative_options:
    getting_started_resources:
        official_docs: https://amperecomputing.com/assets/Ampere_Optimized_Tensorflow_Documentation_v_1_8_0_8ab3f5a054.pdf
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
    other_info: The release notes for the initial Linux/Arm64 support isn't available. Docker images for Aarch64 are available from version 1.4.0 onwards, which officially justifies the Arm support.
 
---
