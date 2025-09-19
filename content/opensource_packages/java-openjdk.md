---
name: Java/OpenJDK
category: Runtimes
description: Java, including its open-source implementation OpenJDK, is a widely-used, high-level, class-based, object-oriented programming language designed for portability across various platforms.
download_url: https://jdk.java.net/archive/
works_on_arm: true
supported_minimum_version:
  version_number: 8
  release_date: 2014/03/18
optional_info:
  homepage_url: https://openjdk.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/performance-of-specjbb2015-on-oci-ampere-a1-compute-instances
    partner_content:
      - display_name: Oracle OCI
        url: https://blogs.oracle.com/javamagazine/post/java-arm-runtime-switches-benchmarks
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/compute/running-java-applications-on-amazon-ec2-a1-instances-with-amazon-corretto/
      - display_name: Microsoft Azure
        url: https://techcommunity.microsoft.com/blog/azurecompute/scaling-azure-arm64-vms-with-microsoft%E2%80%99s-build-of-openjdk-a-performance-testing-/3820435
    official_docs: https://docs.oracle.com/en/java/
  arm_recommended_minimum_version:
    version_number: 11.0.9
    release_date: 2023/06/07
    reference_content: https://community.arm.com/arm-community-blogs/b/architectures-and-processors-blog/posts/java-performance-on-neoverse-n1
    rationale: There is a patch introduced in OpenJDK-11.0.9 and later versions, that reduces the false-sharing cache contention by adding paddings between two volatile variables that are declared side by side. The enhancement isn't arm-specific, but may help improve the performance on all supported architectures.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: null
---
