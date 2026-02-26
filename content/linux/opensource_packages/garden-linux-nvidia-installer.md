---
name: Garden Linux NVIDIA Installer
category: Containers and Orchestration
description: Garden Linux nvidia-installer is a containerised component that compiles and installs NVIDIA GPU kernel drivers for Garden Linux nodes, enabling automated GPU driver provisioning in Kubernetes clusters through the GPU Operator.
download_url: https://github.com/gardenlinux/gardenlinux-nvidia-installer/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.0.4
    release_date: 2024/11/20
 
 
optional_info:
    homepage_url: https://github.com/gardenlinux/gardenlinux-nvidia-installer
    support_caveats: Garden Linux NVIDIA installer does not publish official prebuilt container images for Linux/Arm64, but supports manual Arm64 image builds via TARGET_ARCH=arm64.
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/gardenlinux/gardenlinux-nvidia-installer
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/gardenlinux/gardenlinux-nvidia-installer/releases/tag/0.0.4
    release_notes__recommended_minimum:
    other_info:
 
---
