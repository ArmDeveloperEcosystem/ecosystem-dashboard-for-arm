---
name: Contour
category: Service Mesh
description: Contour is a Kubernetes ingress controller using Envoy proxy.
download_url: https://github.com/projectcontour/contour/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.10.0
    release_date: 2019/03/08


optional_info:
    homepage_url: https://projectcontour.io
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://projectcontour.io/getting-started/
    arm_recommended_minimum_version:
        version_number: 1.22.1
        release_date: 2022/09/08
        reference_content: https://github.com/projectcontour/contour/releases/tag/v1.22.1
        rationale: This release updates Envoy to v1.23.1. This fixes an issue where the arm64 variant of the Envoy image was not built properly.

optional_hidden_info:
    release_notes__supported_minimum: https://hub.docker.com/layers/projectcontour/contour/v1.10.0/images/sha256-fefd6f921648c38ece476672f35c52cf8faac36347494401f6d2225254ae5e1d?context=explore
    release_notes__recommended_minimum:
    other_info: The contour project requires the contour docker images. The support for Arm64 docker image started from version 1.10.0.

---
