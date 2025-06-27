---
name: OneDNN
category: AI/ML
description: OneDNN is an open-source cross-platform performance library of basic building blocks for deep learning applications.
download_url: https://github.com/oneapi-src/oneDNN/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.5
    release_date: 2020/06/17


optional_info:
    homepage_url: https://oneapi-src.github.io/oneDNN/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/machine-learning-inference-on-aws-graviton3
        partner_content: https://aws.amazon.com/blogs/machine-learning/run-machine-learning-inference-workloads-on-aws-graviton-based-instances-with-amazon-sagemaker/
        official_docs: https://uxlfoundation.github.io/oneDNN/
    arm_recommended_minimum_version:
        version_number: 3.7
        release_date: 2025/02/19
        reference_content: https://github.com/uxlfoundation/oneDNN/releases/tag/v3.7
        rationale: This release delivers significant performance and usability improvements for AArch64-based processors. Performance enhancements include improved bf16 matrix multiplication (matmul) with fp32 destination using the Arm Compute Library (ACL), as well as better performance for bf16-to-fp32 reordering, bf16 reordering in general, and bf16 convolution operations via ACL. On the usability front, the release adds support for ACL’s ThreadpoolScheduler through thread_local configuration, fixes a memory inefficiency by enabling proper use of scratchpad memory in ACL matmuls, and makes the ACL matmul primitive thread-safe to support concurrent execution. Together, these changes enhance both computational throughput and multi-threaded execution efficiency on Arm-based platforms.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/oneapi-src/oneDNN/releases/tag/v1.5
    release_notes__recommended_minimum:
    other_info:
---
