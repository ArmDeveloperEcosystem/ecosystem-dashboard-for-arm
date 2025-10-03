---
name: PyTorch
category: AI/ML
description: PyTorch is a Python package that provides two high-level features, first is Tensor computation (like NumPy) with strong GPU acceleration and the second is Deep neural networks built on a tape-based autograd system.
download_url: https://pypi.org/project/torch/#files
works_on_arm: true
supported_minimum_version:
  version_number: 1.8.0
  release_date: 2021/03/04
optional_info:
  homepage_url: https://pytorch.org/
  support_caveats: The AArch64 wheels are present from python 3.9 onwards.
  alternative_options: null
  getting_started_resources:
    official_docs: https://pytorch.org/get-started/locally/
    arm_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/aarch64-docker-images-for-tensorflow-and-pytorch
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/machine-learning/accelerated-pytorch-inference-with-torch-compile-on-aws-graviton-processors
  arm_recommended_minimum_version:
    version_number: 2.0.0
    release_date: 2023/06/22
    reference_content: https://pytorch.org/blog/optimized-pytorch-w-graviton/
    rationale: PyTorch 2.0.0 introduced significant performance optimizations for Arm-based processors, particularly enhancing inference speeds on AWS Graviton instances. These optimizations resulted in up to a 3.5x increase in performance for ResNet-50 models compared to previous releases.
optional_hidden_info:
  release_notes__supported_minimum: https://pypi.org/project/torch/1.8.0/#files
  release_notes__recommended_minimum: null
  other_info: ARM64 support is not mentioned in the release notes. AArch64 wheels are released from version 1.8.0.
---
