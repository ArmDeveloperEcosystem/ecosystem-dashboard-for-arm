---
name: OpenShift
category: Containers and Orchestration
description: OpenShift is a containerization platform that helps developers build, deploy, and manage applications across hybrid cloud environments, providing tools for automation, scalability, and collaboration.
download_url: https://mirror.openshift.com/pub/openshift-v4/aarch64/clients/ocp/
works_on_arm: true
supported_minimum_version:
  version_number: 4.11
  release_date: 2022/08/08
optional_info:
  homepage_url: https://docs.openshift.com/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://docs.openshift.com/container-platform/4.9/installing/installing_sno/install-sno-installing-sno.html
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/software-innovations-with-red-hat-and-arm
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/ibm-redhat/installing-red-hat-openshift-on-aws-in-a-restricted-network-using-aws-secure-token-service/
  arm_recommended_minimum_version:
    version_number: 4.18
    release_date: 2024/12/03
    reference_content: https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/release_notes/ocp-4-18-release-notes#ocp-4-18-new-features-and-enhancements_release-notes
    rationale: In this release, OpenShift Container Platform added support for ARM architecture on AWS user-provisioned infrastructure and on bare-metal installer-provisioned infrastructure.
optional_hidden_info:
  release_notes__supported_minimum: https://docs.openshift.com/container-platform/4.11/release_notes/ocp-4-11-release-notes.html
  release_notes__recommended_minimum: null
  other_info: null
---
