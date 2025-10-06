---
name: OpenCV
category: AI/ML
description: OpenCV (Open Source Computer Vision Library) is an open-source library aimed at real-time computer vision and machine learning applications
download_url: https://github.com/opencv/opencv/tags
works_on_arm: true
supported_minimum_version:
    version_number: 3.4.10
    release_date: 2020/04/04


optional_info:
    homepage_url: https://opencv.org/
    support_caveats:
    alternative_options: 
    getting_started_resources:
        official_docs: https://docs.opencv.org/4.x/d7/d9f/tutorial_linux_install.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 4.11
        release_date: 2025/02/18
        reference_content: https://newsroom.arm.com/blog/arm-kleidicv-opencv-integration
        rationale: OpenCV 4.11.0 integrates Arm's KleidiCV, delivering significant performance enhancements for computer vision workloads on Arm-based devices. This integration leverages Arm architecture features like NEON and SVE2, resulting in up to a 4x performance improvement for various computer vision applications.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: There are no release notes or binaries present for Linux/ARM64. OpenCV version 3.4.10 is installed and tested on the Neoverse N1, using steps mentioned [here](https://docs.opencv.org/3.4/d0/d76/tutorial_arm_crosscompile_with_cmake.html).

---
