---
name: Percona Server for MYSQL
category: Database
description: Percona server for MYSQL is a replacement for any MySQL database. It is fully compatible, advanced, and freely available. It provides greater scalability, superior performance, high availability and enhanced backups.
download_url: https://hub.docker.com/r/percona/percona-server
works_on_arm: true
supported_minimum_version:
  version_number: 8.0.33-25.1-multi
  release_date: 2023/08/02
optional_info:
  homepage_url: https://www.percona.com/mysql/software/percona-server-for-mysql
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Google GCP
        url: https://cloud.google.com/database-migration/docs/mysql/migrate-with-physical-xtrabackup
    official_docs: https://docs.percona.com/percona-server/8.0/docker.html#percona-server-for-mysql-arm64
  arm_recommended_minimum_version:
    version_number: 8.0.33-25
    release_date: 2023/06/05
    reference_content: https://docs.percona.com/percona-server/8.0/yum-repo.html
    rationale: In this version, the RPM builds for RHEL8 and RHEL9 ARM packages with the Aarch64.rpm extension were released.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: There are no Linux/ARM64 specific release notes. Percona server for MYSQL does not release binaries for Linux/ARM64, but the docker images are available for linux/ARM64 in version 8.x as noted in the [MYSQL Software](https://www.percona.com/services/policies/percona-software-support-lifecycle) section. Percona server docker image version 8.0.33-25.1-multi is the first multi-arch docker image available at DockerHub.
---
