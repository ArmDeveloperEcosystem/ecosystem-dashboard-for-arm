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
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/aarch64-docker-images-for-tensorflow-and-pytorch
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/machine-learning/run-machine-learning-inference-workloads-on-aws-graviton-based-instances-with-amazon-sagemaker/
      - display_name: Google GCP
        url: https://cloud.google.com/blog/products/compute/introducing-googles-new-arm-based-cpu
    official_docs: https://www.tensorflow.org/lite/guide/build_arm
  arm_recommended_minimum_version:
    version_number: 2.18.0
    release_date: 2024/10/28
    reference_content: https://blog.tensorflow.org/2024/10/whats-new-in-tensorflow-218.html
    rationale: This version integrated support for NumPy 2.0, which brought improved type promotion rules and computational precision.
optional_hidden_info:
  release_notes__supported_minimum: https://www.tensorflow.org/install/pip#linux
  release_notes__recommended_minimum: null
  other_info: From TensorFlow 2.10 onwards, Linux CPU-builds for Aarch64/ARM64 processors are built, maintained, tested and released by a third party "AWS". Installing the tensorflow package on an ARM machine installs AWS's tensorflow-cpu-aws package.
---
