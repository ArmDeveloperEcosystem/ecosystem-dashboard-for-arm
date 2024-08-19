---
name: Fio
category: Miscellaneous
description: Fio is a flexible I/O tester tool, and is used to save the hassle of writing special test case programs.
download_url: https://brick.kernel.dk/snaps/
works_on_arm: true
supported_minimum_version:
    version_number: 3.28
    release_date: 2021/09/08


optional_info:
    homepage_url: https://github.com/axboe/fio
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://fio.readthedocs.io/en/master/fio_doc.html#building
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes for Linux/ARM64. GitHub releases roll out msi for x86 and x64 only. However, fio can be built and installed from source from version 3.28 and above. The installation is verified with "fio --version". Before version 3.28, build fails commonly on both ARM64 and AMD64 to find linux/raw.h file.

---
