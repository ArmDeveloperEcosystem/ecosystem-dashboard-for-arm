---
name: Elastic Defend
category: Security applications
description: Elastic Defend is an endpoint protection and detection integration in Elastic Agent that delivers EPP, EDR, and SIEM capabilities for Windows, macOS, and Linux systems, providing prevention, detection, response, and deep visibility across endpoints and cloud workloads.
download_url: https://www.elastic.co/downloads/elastic-agent
works_on_arm: true
supported_minimum_version:
    version_number: 7.16.0
    release_date: 2021/12/07
 
 
optional_info:
    homepage_url: https://www.elastic.co/docs/reference/integrations/endpoint
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://www.elastic.co/docs/solutions/security/configure-elastic-defend/install-elastic-defend
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://www.elastic.co/support/matrix
    release_notes__recommended_minimum:
    other_info: Elastic Defend support matrix mentions that Linux Arm support is introduced in version 7.16+ and requires a 5.4+ kernel, with AWS graviton support included. Elastic Defend is not a standalone binary. If you want Elastic Defend, you install Elastic Agent, then enable the Elastic Defend policy in Fleet.
 
---
