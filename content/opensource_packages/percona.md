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
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://docs.percona.com/percona-server/8.0/docker.html#percona-server-for-mysql-arm64
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no Linux/ARM64 specific release notes. Percona server for MYSQL does not release binaries for Linux/ARM64, but the docker images are available for linux/ARM64 in version 8.x as noted in the [MYSQL Software](https://www.percona.com/services/policies/percona-software-support-lifecycle) section. Percona server docker image version 8.0.33-25.1-multi is the first multi-arch docker image available at DockerHub.

---
