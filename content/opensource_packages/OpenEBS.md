---
name: OpenEBS
category: Storage
description: OpenEBS is an open-source containerized storage platform that provides persistent storage for Kubernetes workloads.
download_url: https://github.com/openebs/openebs/releases 
works_on_arm: true
supported_minimum_version:
    version_number: v2.3.0 
    release_date: 2020/11/16


optional_info:
    homepage_url: https://github.com/openebs/openebs
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content: 
        official_docs: https://openebs.io/docs/quickstart-guide/installation
    arm_recommended_minimum_version:
        version_number: 3.3.0
        release_date: 2022/07/15
        reference_content: https://github.com/openebs/openebs/releases/tag/v3.3.0
        rationale: This release focuses on refactoring, maintenance, and critical bug fixes across several storage engines. Notable updates include ARM64 infrastructure support for Mayastor, improved logging and rate limiting in LocalPV, and Helm chart fixes for Jiva. The LocalPV Device and LVM components saw CRD updates, scheduler fixes, and dynamic client refactoring. Enhancements to NDM added better path filtering via custom udev rules.

optional_hidden_info:
    release_notes__supported_minimum: https://github.com/openebs/openebs/releases/tag/v2.3.0 
    release_notes__recommended_minimum:
    other_info: This Project does not release binaries. However, in the release notes of v2.3.0, it is mentioned that the ARM64 support for OpenEBS Data Engines - cStor, Jiva, Local PV (hostpath and device), ZFS Local PV are added.

---

