---
name: Split-evaluator
category: DevOps
description: Split-Evaluator is a wrapper around the Node.js SDK that exposes feature evaluations as a microservice.
download_url: https://github.com/splitio/split-evaluator/tags
works_on_arm: true
supported_minimum_version:
    version_number: 1.0.0
    release_date: 2017/07/29


optional_info:
    homepage_url: https://help.split.io/hc/en-us/articles/360020037072-Split-Evaluator
    support_caveats: Earlier versions require manual npm setup on Arm. Official Arm64 Docker images are available starting from version 2.7.0, simplifying deployment.
    alternative_options:
    getting_started_resources:
        official_docs: https://help.split.io/hc/en-us/articles/360020037072-Split-Evaluator#docker-recommended
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes specifically documenting initial Linux/arm64 support.
        However, the package can be installed manually using "npm install" on Arm systems such as Neoverse N1.
        Official multi-architecture Docker images, including Arm64 support, were introduced starting with version 2.7.0, as noted in the changelog [here](https://github.com/splitio/split-evaluator/blob/master/CHANGES.txt).

---
