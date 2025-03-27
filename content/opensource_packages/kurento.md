---
name: Kurento
category: Web Server
description: Kurento is a WebRTC media server. It offers a set of client APIs to simplify the development of video applications for WWW and smartphone platforms.
download_url:
works_on_arm: FALSE
supported_minimum_version:
    version_number:
    release_date:


optional_info:
    homepage_url: https://doc-kurento.readthedocs.io/en/latest/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://doc-kurento.readthedocs.io/en/latest/user/installation.html#installation-guide
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: It is mentioned in the [official docs](https://doc-kurento.readthedocs.io/en/latest/user/installation.html#installation-guide) that "The only officially supported processor architecture is 64-bit x86, so for other platforms (such as ARM) you will have to build from sources.". However, during [build from source](https://doc-kurento.readthedocs.io/en/latest/dev/dev_guide.html#build-from-sources) for ARM64, dependency installation failed to find kurento-cmake-utils:arm64. There are no ARM64 related issue in the repo and the project is on [bare minimum maintenance mode](https://github.com/Kurento/kurento#project-status).

---
