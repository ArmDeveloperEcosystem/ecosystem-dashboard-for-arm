---
name: OpenResty
category: Web Server
description: OpenResty is a full-fledged web application server by bundling the standard nginx core, lots of 3rd-party nginx modules, as well as most of their external dependencies.
download_url: https://openresty.org/en/linux-packages.html
works_on_arm: true
supported_minimum_version:
  version_number: 1.15.8.1
  release_date: 2019/05/16
optional_info:
  homepage_url: https://openresty.org/en/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/cn/blogs/china/aws-graviton4-accelerates-apache-apisix-message-processing/
    official_docs: https://openresty.org/en/getting-started.html
  arm_recommended_minimum_version:
    version_number: 1.27.1.1
    release_date: 2024/10/15
    reference_content: https://openresty.org/en/ann-1027001001.html
    rationale: This version highlights LuaJIT updated to 2.1-20240815 with various optimizations and bugfixes, including Improved error handling and stack overflow management, enhanced cross-32/64 bit and deterministic bytecode generation, etc. Also added http_v3_module and http_slice_module to official prebuilt packages.
optional_hidden_info:
  release_notes__supported_minimum: https://openresty.org/en/changelog-1015008.html
  release_notes__recommended_minimum: null
  other_info: null
---
