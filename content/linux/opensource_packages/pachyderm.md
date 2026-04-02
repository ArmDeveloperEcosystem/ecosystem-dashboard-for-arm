---
name: Pachyderm
category: Containers and Orchestration
description: Pachyderm acts as a command center for managing data pipelines especially those involving big data processing it excels at keeping track of various data versions ensuring clarity and reproducibility throughout the process.
download_url: https://github.com/pachyderm/pachyderm/releases
works_on_arm: true
supported_minimum_version:
    version_number: v2.3.0
    release_date: 2022/08/19


optional_info:
    homepage_url: https://www.pachyderm.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.pachyderm.com/products/mldm/latest/get-started/first-time-setup/#first-time-setup-2-install-pachctl-cli
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.4.0-nightly.20221108
        release_date: 2022/11/08
        reference_content: https://github.com/pachyderm/pachyderm/releases/tag/v2.4.0-nightly.20221108
        rationale: This version added deploy tests for ARM64 in the CircleCI. It is to be noted that the prior version 2.3.6 already has updated etcd to an image that has an arm64 build.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/pachyderm/pachyderm/releases/tag/v2.3.0
    release_notes__recommended_minimum:
    other_info:

---
