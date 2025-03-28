---
name: Tensorflow
category: AI/ML
description: TensorFlow is an end-to-end open-source platform for machine learning.
download_url: https://pypi.org/project/tensorflow/2.15.0/#files
works_on_arm: true
supported_minimum_version:
    version_number: 2.10.0
    release_date: 2022/09/07


optional_info:
    homepage_url: https://www.tensorflow.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/aarch64-docker-images-for-tensorflow-and-pytorch
        partner_content: https://docs.aws.amazon.com/dlami/latest/devguide/tutorial-graviton-tensorflow.html
        official_docs: https://www.tensorflow.org/lite/guide/build_arm
    arm_recommended_minimum_version:
        version_number: 2.18.0
        release_date: 2024/10/28
        reference_content: https://blog.tensorflow.org/2024/10/whats-new-in-tensorflow-218.html
        rationale: This version integrated support for NumPy 2.0, which brought improved type promotion rules and computational precision. This version also includes updates to the CUDA toolkit and introduced the LiteRT repository, contributing to overall performance improvements.

optional_hidden_info:
    release_notes__supported_minimum: https://www.tensorflow.org/install/pip#linux
    release_notes__recommended_minimum:
    other_info: From TensorFlow 2.10 onwards, Linux CPU-builds for Aarch64/ARM64 processors are built, maintained, tested and released by a third party "AWS". Installing the tensorflow package on an ARM machine installs AWS's tensorflow-cpu-aws package.

---

