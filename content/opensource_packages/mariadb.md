---
name: MariaDB
category: Database
description: MariaDB is a popular open-source relational database management system (RDBMS). It is a robust, scalable, and secure RDBMS that continues to evolve with the contributions of its community. It provides the tools and flexibility to meet your database needs.
download_url: https://archive.mariadb.org/
works_on_arm: true
supported_minimum_version:
  version_number: mariadb-10.3.7
  release_date: 2018/05/24
optional_info:
  homepage_url: https://mariadb.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://mariadb.com/kb/en/getting-installing-and-upgrading-mariadb/
    arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/mariadb/
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/database/powering-amazon-rds-with-aws-graviton3-benchmarks/
  arm_recommended_minimum_version:
    version_number: 11.8.0
    release_date: 2024/12/18
    reference_content: https://mariadb.com/kb/en/mariadb-11-8-0-release-notes/
    rationale: This release supports aarch64 SIMD instructions in mhnsw algorithm. However, version 11.8.0 is an alpha release, so consider switching to 11.8.1 for the stable functionality.
optional_hidden_info:
  release_notes__supported_minimum: https://archive.mariadb.org/mariadb-10.3.7/repo/ubuntu/dists/bionic/main/binary-arm64/
  release_notes__recommended_minimum: null
  other_info: Here is the [PR](https://github.com/MariaDB/server/pull/773/files) to fix compilation issues for AArch64.
---
