---
name: KubeEdge
category: Containers and Orchestration
description: KubeEdge is built upon Kubernetes and extends native containerized application orchestration and device management to hosts at the Edge.
download_url: https://github.com/kubeedge/kubeedge/releases
works_on_arm: true
supported_minimum_version:
  version_number: 1.3.0
  release_date: 2020/05/15
optional_info:
  homepage_url: https://kubeedge.io/en/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://kubeedge.io/docs/category/developer-guide/
    arm_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/q-a-with-priyanka-sharma-for-arm-devsummit-2020
    partner_content:
      - display_name: Alibaba Cloud
        url: https://www.alibabacloud.com/blog/openyurt-the-practice-of-extending-native-kubernetes-to-the-edge_597903
  arm_recommended_minimum_version:
    version_number: 1.20.0
    release_date: 2025/01/21
    reference_content: https://github.com/kubeedge/kubeedge/blob/master/CHANGELOG/CHANGELOG-1.20.md
    rationale: This version introduces batch node operation support, enabling large-scale edge deployments to perform join, reset, and upgrade actions across nodes via a single configuration. The release expands keadm ctl capabilities with pod and device operations (logs, exec, describe) for offline edge scenarios. A Java Mapper-Framework is now available, easing multi-language custom mapper development. EdgeApplications now support node label selectors, decoupling them from NodeGroups. Additionally, IPv6 support is added for CloudHub-EdgeHub, and Kubernetes is upgraded to v1.30.7.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/kubeedge/kubeedge/blob/master/CHANGELOG/CHANGELOG-1.3.md#v130
  release_notes__recommended_minimum: null
  other_info: ARM64 support is not mentioned in any release notes, but the first binary for ARM64 was released for version v1.3.0.
---
