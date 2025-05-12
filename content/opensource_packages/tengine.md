---
name: Tengine
category: Web Server
description: Tengine is a web server originated by Taobao, the largest e-commerce website in Asia. Tengine is based on the Nginx HTTP server and has many advanced features.
download_url: https://tengine.taobao.org/download.html
works_on_arm: true
supported_minimum_version:
    version_number: 2.4.0
    release_date: 2023/02/08


optional_info:
    homepage_url: https://tengine.taobao.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://tengine.taobao.org/documentation.html
    arm_recommended_minimum_version:
        version_number: 3.0.0
        release_date: 2023/07/20
        reference_content: https://github.com/alibaba/tengine/releases/tag/3.0.0
        rationale: This version added new features like dynamically reconfigure the servers, locations and upstreams without reloading or restarting worker processes, HTTP/3 support,  high-speed UDP transmission with kernel-bypass, dynamically reconfigure canary routing based on standard and custom HTTP headers, header value, and weights, and dynamically reconfigure timeout setting, SSL Redirects, CORS and enabling/disabling robots for the ingress/path.


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/alibaba/tengine/releases/tag/2.4.0
    release_notes__recommended_minimum:
    other_info: Installation and testing are done using released source code tar for specified version.

---
