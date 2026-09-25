---
name: Rafay Kubernetes Manager
vendor: Rafay Systems
category: Containers and Orchestration
description: Rafay Kubernetes Manager provides centralized lifecycle management, automation, governance, monitoring, and self-service for Kubernetes clusters across public cloud, data center, edge, and hybrid environments.
product_url: https://rafay.co/solutions/kubernetes-manager
works_on_arm: true
release_date_on_arm: 2021/06/25


optional_info:
    homepage_url: https://rafay.co
    support_caveats: Arm64 support is explicitly documented for Rafay's minimal cluster blueprint. Architecture support for individual optional add-ons and customer workloads may depend on the corresponding container images/components.
    alternative_options: Red Hat Advanced Cluster Management, Rancher/SUSE Rancher, VMware Tanzu, Google Anthos
    getting_started_resources:
        official_docs: https://docs.rafay.co/learn/overview/
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/rafay-eks/
        vendor_announcement: https://docs.rafay.co/releasenotes/2021/#v153
optional_hidden_info:
    other_info: Rafay documentation states that both arm64 and amd64 architectures are supported with its minimal cluster blueprint (https://docs.rafay.co/blueprints/minimal_blueprint/). The Rafay management operator is deployed into customer Kubernetes clusters and securely communicates with the Rafay Controller.

---
