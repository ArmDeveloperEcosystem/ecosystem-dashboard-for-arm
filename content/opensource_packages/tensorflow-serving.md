---
name: Tensorflow Serving
category: AI/ML
description: TensorFlow Serving is a high-performance and flexible serving system for machine learning models, which deals with the inference aspect of machine learning, taking models after training and managing their lifetimes, providing clients with versioned access via a high-performance, reference-counted lookup table.
download_url: https://github.com/tensorflow/serving/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.10.0-rc0
    release_date: 2022/08/05
 
 
optional_info:
    homepage_url: https://www.tensorflow.org/tfx/guide/serving
    support_caveats: Build and setup via docker isn't available for ARM64 (as of May 2025), since tensorflow/serving docker images are only available for Linux/AMD64. Not officially recommended, but consider [install without docker](https://github.com/tensorflow/serving/blob/master/tensorflow_serving/g3doc/setup.md) for ARM platforms.
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://www.tensorflow.org/tfx/serving/setup
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/tensorflow/serving/releases/tag/2.10.0-rc0
    release_notes__recommended_minimum:
    other_info: The minimum version adds aarch64 mkl bazel config to enable onednn+acl backend. [This PR](https://github.com/tensorflow/serving/pull/1953) confirms that the model server tests run successfully on the aarch64 platform.
 
---
