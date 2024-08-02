---
name: Drone CI
category: DevOps
description: Drone is a Continuous Integration platform that uses a powerful, cloud native pipeline engine, which allows busy teams to automate their build, test and release workflows.
download_url: https://hub.docker.com/r/drone/drone/tags
works_on_arm: true
supported_minimum_version:
    version_number: 1.0
    release_date: 2019/04/17


optional_info:
    homepage_url: https://www.drone.io/
    support_caveats: Drone is still availible. However, Gitness is being invested in as the next generation of Drone. Where Drone focused on continuous integration, Gitness adds source code hosting, bringing code management and pipelines closer together.
    alternative_options: Gitness
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/drone-io-ci-cd-tool-for-developers
        partner_content:
        official_docs: https://docs.drone.io/
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum: https://blog.drone.io/drone-1/
    release_notes__recommended_minimum:
    other_info: Drone 1.0 introduces support for multiple operating systems and architectures, including Linux arm64. Drone server and the runner can be downloaded and can be setup using drone and drone-runner-docker docker images, which are available for Linux/ARM64 at DockerHub from version 1.0.

---
