---
name: NGINX
category: Web Server
description: NGINX is open-source software for web serving, reverse proxying, caching, load balancing, media streaming etc.
download_url: https://nginx.org/en/download.html
works_on_arm: true
supported_minimum_version:
  version_number: 1.7.7
  release_date: 2014/10/28
optional_info:
  homepage_url: https://www.nginx.com/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/nginx/
    partner_content:
      - display_name: Microsoft Azure
        url: https://amperecomputing.com/briefs/nginx-on-azure-brief
    official_docs: https://www.nginx.com/resources/wiki/start/
  arm_recommended_minimum_version:
    version_number: 1.20.1
    release_date: 2022/12/14
    reference_content: https://community.arm.com/arm-community-blogs/b/servers-and-cloud-computing-blog/posts/improve-nginx-performance-up-to-32-by-deploying-on-alibaba-cloud-yitian-710-instances
    rationale: This blog shows that NGINX version 1.20.1 deployed on Yitian 710 based ECS provides up to 32% more throughput in compared to the equivalent x86 based ECS instances.
optional_hidden_info:
  release_notes__supported_minimum: https://www.nginx.com/blog/nginx-plus-r5-released/
  release_notes__recommended_minimum: null
  other_info: The minimum supported version(1.7.7) is part of the NGINX Plus Release 5(R5).
---
