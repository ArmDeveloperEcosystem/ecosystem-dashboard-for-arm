---
name: Harbor
category: Containers and Orchestration
description: An open source trusted cloud native registry project that stores, signs, and scans content.
download_url: https://github.com/goharbor/harbor/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.7.1
    release_date: 2023/04/17


optional_info:
    homepage_url: https://goharbor.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://goharbor.io/docs/2.10.0/install-config/
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Harbor version v2.7.1 on Docker Hub for ARM64 is released by Bitnami. Some of the Docker images are [harbor-core](https://hub.docker.com/layers/bitnami/harbor-core/2.7.1/images/sha256-b80969a6711911ce399dcd9d31823a79c97be9169dde5a45264d3ead3c0baa1c?context=explore), [harbor-registry](https://hub.docker.com/layers/bitnami/harbor-registry/2.7.1/images/sha256-3aa6b709d8068906e3609257e90e27637b24bbdffd4b65c98d74b8285456cecc?context=explore), [harbor-registryctl](https://hub.docker.com/layers/bitnami/harbor-registryctl/2.7.1/images/sha256-4caeaefc6bcf6bd48effdb43830223bb984c4f4fb52bd7bfaf83232bd227aea6?context=explore) and [harbor-jobservice](https://hub.docker.com/layers/bitnami/harbor-jobservice/2.7.1/images/sha256-8b223e692788817dc23decd2bc465808497e04538d6b03dfd6b34312c3e2848b?context=explore) all confirming the release date for ARM64. Deployed Harbor using BitnamiCharts on a Kubernetes cluster, where bitnamicharts/harbor v20.0.0 (CHART VERSION) and harbor v2.10.0 (APP VERSION) work successfully. The CHART VERSION was released on 04/03/2024. Please note that older versions of bitnamicharts/harbor from v19.0.0 to v16.0.0 do not support ARM64 and the status of the pods for these versions shows ImagePullBackOff, ErrImagePull and CrashLoopBackOff.

---
