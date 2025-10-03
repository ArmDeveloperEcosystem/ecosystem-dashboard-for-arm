---
name: Apache Apisix
category: Web Server
description: Apache APISIX is an open-source, dynamic, scalable API gateway that provides rich traffic management features such as load balancing, dynamic upstream, canary release, service mesh, and more.
download_url: https://github.com/apache/apisix/tags
works_on_arm: true
supported_minimum_version: 
    version_number: 0.9
    release_date: 2019/11/15


optional_info:
    homepage_url: https://apisix.apache.org/
    support_caveats:
    alternative_options: 
    getting_started_resources:
        official_docs: https://apisix.apache.org/docs/apisix/installation-guide/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.14.1
        release_date: 2022/06/07
        reference_content: https://apisix.apache.org/blog/2022/06/07/installation-performance-test-of-apigateway-apisix-on-aws-graviton3/
        rationale: This blog shows that in a network IO dense computing scenario such as API Gateway, Apisix running on AWS Graviton3 improves the performance by 76% compared to AWS Graviton2, while reducing latency by 38%. This data is even better than the official data given by AWS mentioned at the beginning of blog (25% performance improvement).


optional_hidden_info:
    release_notes__supported_minimum: https://github.com/apache/apisix/blob/v0.9/README.md
    release_notes__recommended_minimum: 
    other_info:  0.9 is the first version that carries in the Readme that APISIX has been installed and tested on ARM64 Ubuntu 18.04. 

---
