---
name: Exechealthz
category: DevOps
description: Exec healthz server is a sidecar container, which serves as a liveness-exec-over-http bridge by isolating pods from the idiosyncrasies of container runtime exec implementations.
download_url: https://github.com/kubernetes-retired/contrib/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.6.3
    release_date: 2016/06/09


optional_info:
    homepage_url: https://github.com/kubernetes-retired/contrib/tree/master/exec-healthz
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/kubernetes-retired/contrib/tree/master/exec-healthz#how-to-release
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/kubernetes-retired/contrib/tree/0.6.3/exec-healthz
    release_notes__recommended_minimum:
    other_info: It's mentioned in the Readme.md in version 0.6.3 that "The exechealthz Makefile supports multiple architecures, which means it may cross-compile and build a docker image easily".

---
