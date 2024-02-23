---
name: Fluentd
category: Logging
description: Fluentd collects events from various data sources and writes them to files, RDBMS, NoSQL, IaaS, SaaS, Hadoop and so on. Fluentd helps to unify the logging infrastructure.
download_url: https://github.com/fluent/fluentd/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.12.32
    release_date: 3/2/2017


optional_info:
    homepage_url: https://www.fluentd.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://community.arm.com/arm-community-blogs/b/tools-software-ides-blog/posts/enabling-cloud-native-experience-across-a-diverse-and-secure-edge-ecosystem
        partner_content: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-setup-logs.html
        official_docs: https://docs.fluentd.org/installation/install-by-gem
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes available for ARM64. v0.12.32 successfully gets installed on the Neoverse N1 (Installed via gem). Before v0.12.32 version, installation issues are seen on both ARM64 and AMD64. The development/support of Fluentd v0.12 has been ended. [It is not recommended to use v0.12 for the deployment](https://docs.fluentd.org/v/0.12/). It is advised to use v1 for deployment.

---
