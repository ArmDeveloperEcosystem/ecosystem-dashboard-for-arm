---
name: DHCP (Dynamic Host Configuration Protocol)
category: Networking
description: The Dynamic Host Configuration Protocol (DHCP) facilitates the automatic assignment of IP addresses and network settings to devices on a network. This process allows devices to connect without manual configuration of IP addresses, thereby streamlining network management and enhancing overall performance.
download_url: https://ftp.isc.org/isc/dhcp
works_on_arm: true
supported_minimum_version:
    version_number: 4.2.4
    release_date: 2014/04/07


optional_info:
    homepage_url: https://www.isc.org/dhcp/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://developer.arm.com/documentation/dui0102/g/using-the-dhcp-utility
        partner_content: 
        official_docs: https://gitlab.isc.org/isc-projects/dhcp/-/blob/master/README?ref_type=heads
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale: 

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done using `apt install isc-dhcp-serve` on ubuntu 14.04 and above versions. ISC announced that support for ISC DHCP would end by late 2022. They introduced a new DHCP server, Kea, which is intended to [replace ISC DHCP](https://www.isc.org/dhcp_migration) in most server deployments.

---
