---
name: Elastic Fleet Server
category: Monitoring/Observability
description: Elastic Fleet Server is a subprocess that runs inside an Elastic Agent and acts as the control plane between Elastic Fleet and Elastic Agents, distributing policies, collecting status, and coordinating actions at scale.
download_url: https://github.com/elastic/fleet-server/tags
works_on_arm: true
supported_minimum_version:
    version_number: 7.12.0
    release_date: 2021/03/23
 
 
optional_info:
    homepage_url: https://www.elastic.co/docs/reference/fleet/fleet-server
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://www.elastic.co/docs/reference/fleet/add-fleet-server-cloud
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
    other_info: Elastic fleet server comes integrated with Elastic Agent. There are no Linux/Arm64 support matrix for Elastic Fleet Server. Elastic Agent version 7.12.0 started releasing Linux Aarch64 artifacts. Hence, it is expected that Fleet Server also supports Linux Aarch64 from version 7.12.0 onwards. Please see [this discussion forum](https://discuss.elastic.co/t/fleet-server-for-arm64/274900) for more details.
 
---
