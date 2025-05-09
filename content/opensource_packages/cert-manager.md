---
name: Cert-manager
category: Security applications
description: Cert-manager adds certificates and certificate issuers as resource types in Kubernetes clusters, and simplifies the process of obtaining, renewing and using those certificates.
download_url: https://github.com/cert-manager/cert-manager/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.7.0
    release_date: 2019/03/11


optional_info:
    homepage_url: https://cert-manager.io/ 
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://cert-manager.io/docs/installation/
    arm_recommended_minimum_version:
        version_number: 1.12.0
        release_date: 2023/05/19
        reference_content: https://github.com/cert-manager/cert-manager/releases/tag/v1.12.0
        rationale: This version fixes development environment and go vendoring on Linux arm64. Alongwith, cert-manager v1.12 brings support for JSON logging, a lower memory footprint, support for ephemeral service account tokens with Vault, improved dependency management and support for the ingressClassName field.

optional_hidden_info:
    release_notes__supported_minimum: https://release-next--cert-manager-website.netlify.app/docs/releases/release-notes/release-notes-0.7
    release_notes__recommended_minimum:
    other_info:

---
