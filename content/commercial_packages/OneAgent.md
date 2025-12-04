---
name: Dynatrace OneAgent
vendor: Dynatrace
category: Monitoring/Observability
description: Dynatrace OneAgent is a unified, code-injecting monitoring agent that automatically collects deep metrics across hosts, processes, and applications, delivering code-level insights and real-user monitoring through automatic JavaScript instrumentation.
product_url: https://www.dynatrace.com/platform/oneagent/
works_on_arm: true
release_date_on_arm: 2020/04/06


optional_info:
    homepage_url: https://www.dynatrace.com/platform/oneagent/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.dynatrace.com/docs/ingest-from/dynatrace-oneagent/installation-and-operation/linux/installation/install-oneagent-on-linux
        arm_content:
        vendor_announcement: https://docs.dynatrace.com/docs/ingest-from/technology-support#nginx
optional_hidden_info:
    other_info: The Technology support page mentions that Arm64 (AArch64) support was introduced with OneAgent version 1.189. Version 1.189 release notes also mentions that this version fixed problem in which OneAgent failed to load on Arm in a full-stack setup. Please see [this](https://docs.dynatrace.com/docs/whats-new/oneagent/sprint-189#oneagent-sprint-189-ga-Java). Dynatrace OneAgent is a proprietary, commercially licensed product. Installation requires authentication into a Dynatrace SaaS or Managed tenant, and the installer is generated per-tenant with restricted permissions. Because binaries, including Linux/Arm64, are not publicly accessible and must be downloaded through the official tenant-specific workflow, OneAgent is not an open-source or freely distributable package.
---
