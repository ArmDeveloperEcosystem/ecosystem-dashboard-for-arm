---
name: Ipvsadm
category: Miscellaneous
description: Ipvsadm administers the IP Virtual Server services offered by the Linux kernel with IPVS support to create a wide range of load-balancer setups.
download_url: https://github.com/e7e5/ipvsadm/tags
works_on_arm: true
supported_minimum_version:
    version_number: 1.27
    release_date: 2013/09/02


optional_info:
    homepage_url: https://github.com/e7e5/ipvsadm
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/e7e5/ipvsadm/blob/master/README
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no Linux/ARM64 release notes. However, version 1.27 can be built from source on both x86_64 and ARM64 platforms using make. Also, following packages are required before building, "apt-get install libnl-3-dev libnl-genl-3-dev build-essential libpcap-dev libpopt-dev".

---
