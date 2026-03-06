---
name: Gardener external-dns-management
category: Containers and Orchestration
description: Gardener external-dns-management is a Kubernetes-based DNS controller framework that manages external DNS records for clusters by decoupling DNS source objects (e.g., Services, Ingresses) from DNS provisioning environments. It introduces custom resources like DNSEntry and DNSProvider to dynamically create and manage DNS records across multiple cloud DNS providers.
download_url: https://console.cloud.google.com/artifacts/docker/gardener-project/europe/releases/dns-controller-manager
works_on_arm: true
supported_minimum_version:
    version_number: 0.23.1
    release_date: 2025/02/10
 
 
optional_info:
    homepage_url: https://github.com/gardener/external-dns-management
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/gardener/external-dns-management#quick-start
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 0.26.0
        release_date: 2025/07/25
        reference_content: https://github.com/gardener/external-dns-management/releases/tag/v0.26.0
        rationale: In this release, Linux/Arm64 image build was fixed.
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/gardener/external-dns-management/releases/tag/v0.23.1
    release_notes__recommended_minimum:
    other_info:
 
---
