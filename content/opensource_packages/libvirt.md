---
name: Libvirt
category: Miscellaneous
description: Libvirt provides a toolkit for managing virtualization platforms. Libvirt comes under the open-source licenses, and is accessible from C, Python, Perl, Go, and many more.
download_url: https://libvirt.org/downloads.html
works_on_arm: true
supported_minimum_version:
    version_number: 1.1.4
    release_date: 2013/11/04


optional_info:
    homepage_url: https://libvirt.org/index.html
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://libvirt.org/compiling.html
    arm_recommended_minimum_version:
        version_number: 11.1.0
        release_date: 2025/03/03
        reference_content: https://libvirt.org/news.html#v11-1-0-2025-03-03
        rationale: This version introduced a bug fix which addresses a crash in virtqemud when starting a domain with a custom CPU model on hosts where the CPU model is undetectable — an issue primarily affecting AArch64 (ARM64) hosts. The problem, introduced in libvirt 10.9.0, caused qemu to fail initialization on such systems due to the missing CPU model information.

optional_hidden_info:
    release_notes__supported_minimum: https://gitlab.com/libvirt/libvirt/-/blob/v1.1.4/docs/news.html.in?ref_type=tags#L15
    release_notes__recommended_minimum:
    other_info: The official libvirt [NEWS page](https://libvirt.org/news.html#) shows no release notes for v1.1.4. However, the gitlab repo for libvirt has the initial AArch64 support mentioned in the [news.html](https://gitlab.com/libvirt/libvirt/-/blob/v1.1.4/docs/news.html.in?ref_type=tags#L15) file in version 1.1.4.

---
