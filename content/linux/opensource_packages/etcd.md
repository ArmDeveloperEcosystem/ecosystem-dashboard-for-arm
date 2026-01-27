---
name: Etcd
category: Miscellaneous
description: Etcd is a distributed reliable key-value store for the most critical data of a distributed system.
download_url: https://github.com/etcd-io/etcd/releases
works_on_arm: true
supported_minimum_version:
  version_number: v3.2.11
  release_date: 2017/12/06
optional_info:
  homepage_url: https://etcd.io/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://etcd.io/docs/latest/
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/improve-etcd-performance-by-18-percent-by-deploying-on-aws-graviton2
    partner_content:
      - display_name: Ampere
        url: https://amperecomputing.com/blogs/ampere-computing-and-cncf-supporting-arm-native-ci-for-ncf-projects
  arm_recommended_minimum_version:
    version_number: 3.5.19
    release_date: 2025/03/05
    reference_content: https://github.com/etcd-io/etcd/blob/main/CHANGELOG/CHANGELOG-3.5.md#v3519-2025-03-05
    rationale: Version 3.5.19 addresses a performance regression related to uncertain compaction sleep intervals, which could enhance overall performance. Kindly refer [here](https://github.com/etcd-io/etcd/pull/19405).
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/etcd-io/etcd/releases/tag/v3.2.11
  release_notes__recommended_minimum: null
  other_info: There are no release notes for ARM64. However, aarch64 binaries are published from v3.2.11 release.
---
