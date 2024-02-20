---
name: Volcano
category: Scheduling & Orchestration
description: Volcano is a Cloud Native Batch System. It provides a suite of mechanisms that are commonly required by many classes of batch & elastic workload including machine learning/deep learning, bioinformatics/genomics and other "big data" applications.
download_url: https://hub.docker.com/u/volcanosh
works_on_arm: true
supported_minimum_version:
    version_number: 1.1.0
    release_date: 30/10/2020


optional_info:
    homepage_url: https://volcano.sh/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content: https://docs.aws.amazon.com/emr/latest/EMR-on-EKS-DevelopmentGuide/tutorial-volcano.html
        official_docs: https://volcano.sh/en/docs/installation/#install-with-yaml-files
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/volcano-sh/volcano/releases/tag/v1.1.0
    release_notes__recommended_minimum:
    other_info: Volcano does not release architecture specific binaries. The docker images are available for linux/arm64 [here](https://hub.docker.com/u/volcanosh).

---
