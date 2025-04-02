---
name: Barbican
category: DevOps
description: Barbican is a REST API, used for the secure storage, provisioning, and management of secrets.
download_url: https://github.com/openstack/barbican/tags
works_on_arm: true
supported_minimum_version:
    version_number: 2.0.0
    release_date: 2016/04/07


optional_info:
    homepage_url: https://opendev.org/openstack/barbican
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://docs.openstack.org/barbican/latest/install/install-ubuntu.html#install-and-configure-components
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes for Linux/ARM64. Barbican can be installed via "apt-get install barbican-api barbican-keystone-listener barbican-worker" with minimum version 2.0.0 on Ubuntu Xenial, and version 14.0.0 on Ubuntu Jammy. Packages aren't found on Ubuntu Trusty apt list.

---
