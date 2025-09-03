---
name: Caddy
category: Web Server
description: Caddy is an open-source web server that automatically handles HTTPS, simplifying web deployment with its easy configuration and built-in security features.
download_url: https://github.com/caddyserver/caddy/releases
works_on_arm: true
supported_minimum_version:
  version_number: 0.8.3
  release_date: 2016/04/26
optional_info:
  homepage_url: https://caddyserver.com/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
    official_docs: https://caddyserver.com/docs/install
  arm_recommended_minimum_version:
    version_number: 2.8.0
    release_date: 2024/05/31
    reference_content: https://news.tuxmachines.org/n/2024/05/31/Caddy_2_8_Web_Server_Is_Here_with_Many_Improvements.shtml
    rationale: Caddy 2.8.0 introduced numerous enhancements, including support for ACME Renewal Information (ARI) and proxying to backends over HTTP/3. While these improvements are not exclusively targeted at Arm architectures, they contribute to overall performance and feature set enhancements that benefit deployments on Arm-based servers.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/caddyserver/caddy/releases/tag/v0.8.3
  release_notes__recommended_minimum: null
  other_info: Linux/ARM64 release notes are not available. The first Linux/ARM64 tar is available in version 0.8.3.
---
