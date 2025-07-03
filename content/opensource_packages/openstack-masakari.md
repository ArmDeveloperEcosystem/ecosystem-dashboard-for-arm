---
name: Openstack Masakari
category: DevOps
description: Masakari is the Virtual Machine High Availability (VMHA) service for OpenStack that automatically recovers KVM-based VMs from failures like VM crashes or host issues, and provides APIs to manage the recovery process.
download_url: https://github.com/openstack/masakari/tags
works_on_arm: true
supported_minimum_version:
    version_number: 6.0.0
    release_date: 2018/08/30
 
 
optional_info:
    homepage_url: https://docs.openstack.org/masakari/latest/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://docs.openstack.org/masakari/latest/#installation
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes for Linux/ARM64. Maskari version 6.0.0 is the minimum that can be installed on Ubuntu Bionic via "apt-get install masakari-api masakari-engine python3-masakari". Similarly, Maskari version 9.0.0 is the minimum that can be installed via apt on Ubuntu Bionic.
 
---
