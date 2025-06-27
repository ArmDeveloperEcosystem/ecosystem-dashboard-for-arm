--- 
name: Container Network Interface
category: Networking
description: Container Network Interface is a specification to configure network interfaces in Linux containers.
download_url: https://github.com/containernetworking/cni/releases
works_on_arm: true 
supported_minimum_version: 
    version_number: 0.4.0 
    release_date: 2017/01/14

  
optional_info:
    homepage_url: https://www.cni.dev/
    support_caveats: 
    alternative_options: 
    getting_started_resources: 
        arm_content: https://community.arm.com/arm-research/b/articles/posts/a-smarter_2d00_cni-for-kubernetes-on-the-edge
        partner_content: https://static.linaro.org/connect/lvc20/presentations/LVC20-115-0.pdf
        official_docs: https://www.cni.dev/docs/
    arm_recommended_minimum_version: 
        version_number: 1.2.0
        release_date: 2024/04/16
        reference_content: https://github.com/containernetworking/cni/releases/tag/v1.2.0
        rationale: CNI v1.2.0 introduces support for CNI spec v1.1.0 with two major enhancements - a new GC (Garbage Collection) verb to clean up stale IPAM reservations and cached attachments, and a STATUS verb allowing plugins to report readiness for ADD operations. These improvements help runtimes like containerd and cri-o detect plugin health more reliably.
  
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/containernetworking/cni/releases/tag/v0.4.0
    release_notes__recommended_minimum: 
    other_info:
---
