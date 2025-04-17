---
name: EMQX (open source)
category: Messaging/Comms
description: EMQX is the core product of EMQ Technologies, and EMQX open source is a community-supported open-source MQTT broker. EMQX is a reliable and scalable MQTT messaging platform.
download_url: https://github.com/emqx/emqx/releases
works_on_arm: true
supported_minimum_version:
    version_number: 4.2.0
    release_date: 2020/05/09


optional_info:
    homepage_url: https://www.emqx.com/en/about
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://docs.emqx.com/en/emqx/latest/getting-started/getting-started.html#install-emqx
    arm_recommended_minimum_version:
        version_number: 5.0.0
        release_date: 2022/06/17
        reference_content: https://github.com/emqx/emqx/releases/tag/v5.0.0
        rationale: This release introduced an extension to the Mnesia database, named 'Mria', which allows more nodes to join the cluster as 'replicants'. With this, EMQX team managed to achieve 100 million MQTT clients connecting to a 23-node Mria cluster. It's a 3 times larger cluster size compared to a typical version 4 cluster, with 10 times more capacity.

optional_hidden_info:
    release_notes__supported_minimum: https://docs.emqx.com/en/emqx/latest/changes/changes-ce-v4.html#_4-2-0
    release_notes__recommended_minimum:
    other_info:

---
