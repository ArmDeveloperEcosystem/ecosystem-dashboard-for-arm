---
name: gRPC-java
category: Messaging/Comms
description: gRPC-Java is a framework tailored for creating microservices that utilize remote procedure calls (RPC) for communication. It employs Protocol Buffers for efficient serialization of data, allowing seamless interaction between services implemented in various programming languages.
download_url: https://github.com/grpc/grpc-java/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.26.0
    release_date: 2019/12/19

optional_info:
    homepage_url: https://grpc.io/docs/languages/java/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://grpc.io/docs/languages/java/quickstart/
    arm_recommended_minimum_version:
        version_number: 1.55.1
        release_date: 2023/05/09
        reference_content: https://github.com/grpc/grpc-java/releases/tag/v1.55.1
        rationale: Protoc-gen-grpc-java binaries for Linux ARM and PPC are now built using Ubuntu 18.04. They will no longer work on Ubuntu 16.04 and Debian 9. This change ensures better compatibility and performance on modern ARM64 systems. The release also stabilized frequently used compression APIs, which can lead to improved performance and reliability in ARM64 environments.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/grpc/grpc-java/releases/tag/v1.26.0
    release_notes__recommended_minimum:
    other_info: Support for cross-compiling to the aarch64 platform was introduced in version 1.26.0, with the relevant pull request available [here](https://github.com/grpc/grpc-java/pull/6441).

---
