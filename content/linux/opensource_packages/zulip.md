---
name: Zulip
category: Messaging/Comms
description: Zulip is an organized team chat app, designed for efficient communication.
download_url: https://github.com/zulip/zulip/releases
works_on_arm: true
supported_minimum_version:
    version_number: 4.10
    release_date: 2022/02/25


optional_info:
    homepage_url: https://zulip.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://zulip.readthedocs.io/en/latest/overview/readme.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 5.0
        release_date: 2022/03/29
        reference_content: https://zulip.readthedocs.io/en/latest/overview/changelog.html#zulip-server-5-0
        rationale: This version introduced comprehensive support for ARM architectures, added support for installation on ARM platforms (including Mac M1). The highlights include the removing support for Ubuntu 18.04, which no longer receives upstream security support for key Zulip dependencies, added web-public streams, new formatting buttons and improved UI. Kindly refer [here](https://blog.desdelinux.net/en/zulip-5-arrives-with-support-for-arm-redesign-improvements-and-more/) for more.


optional_hidden_info:
    release_notes__supported_minimum: https://zulip.readthedocs.io/en/latest/overview/changelog.html#zulip-server-4-10
    release_notes__recommended_minimum:
    other_info: ARM64 support is added to everything in version 4.10, except wal-g. Kindly consider [this](https://github.com/zulip/zulip/issues/21070) issue.

---
