---
name: Litmus
category: Chaos Engineering
description: Litmus is a toolset to do cloud-native chaos engineering, and provides tools to orchestrate chaos on Kubernetes to help SREs find weaknesses in their deployments.
download_url: https://hub.docker.com/r/litmuschaos/chaos-operator/tags
works_on_arm: true
supported_minimum_version:
    version_number: 1.9.0
    release_date: 15/10/2020


optional_info:
    homepage_url: https://litmuschaos.io/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://docs.litmuschaos.io/docs/getting-started/installation#install-litmus-using-kubectl
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/litmuschaos/litmus/releases/tag/1.9.0
    release_notes__recommended_minimum:
    other_info: The first multiarch litmuschaos/chaos-operator docker image wih ARM64 manifest is released in v1.9.0 with the tag multiarch-1.9.0, which can be used during litmus installation (v1.9.0) via kubectl. Kindly refer [here](https://hub.docker.com/layers/litmuschaos/chaos-operator/multiarch-1.9.0/images/sha256-f029282dcdf38dbe17550f83e7775e3849747c4946f554875ad36e9dd9b4fc9b?context=explore).

---
