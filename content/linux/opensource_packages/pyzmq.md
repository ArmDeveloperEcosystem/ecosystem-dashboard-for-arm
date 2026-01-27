---
name: PyZMQ
category: Messaging/Comms
description: PyZMQ is a python wrapper for the ZeroMQ library, which provides a high-performance asynchronous messaging framework.
download_url: https://pypi.org/project/pyzmq/#files
works_on_arm: true
supported_minimum_version:
    version_number: 21.0.0
    release_date: 2021/01/14

optional_info:
    homepage_url: https://pyzmq.readthedocs.io/en/latest/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://pyzmq.readthedocs.io/en/latest/howto/build.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 23.2.1
        release_date: 2022/08/12
        reference_content: https://pyzmq.readthedocs.io/en/latest/changelog.html#id22
        rationale: This release introduces Python 3.11 wheel support, improving compatibility with the latest Python versions. Additionally, Linux AArch64 wheels now include the same libzmq (v4.3.4) as other platforms. This consistency was achieved by switching to native ARM builds using CircleCI, enhancing reliability and alignment across architectures.

optional_hidden_info:
    release_notes__supported_minimum: https://pyzmq.readthedocs.io/en/latest/changelog.html#id31
    release_notes__recommended_minimum:
    other_info: The project rolls out Linux-AArch64 wheels from version [21.0.0](https://pypi.org/project/pyzmq/21.0.0/#files) onwards.
---

