---
name: Druid
category: Databases - Big-data
description: Druid is a high performance, real-time analytics database that delivers sub-second queries on streaming and batch data at scale and under load.
download_url: https://archive.apache.org/dist/druid/
works_on_arm: true
supported_minimum_version:
  version_number: 0.17.0
  release_date: 2020/01/26
optional_info:
  homepage_url: https://druid.apache.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Amazon AWS
        url: https://docs.aws.amazon.com/solutions/latest/scalable-analytics-using-apache-druid-on-aws/configure-the-solution.html
    official_docs: https://druid.apache.org/docs/latest/tutorials/
  arm_recommended_minimum_version:
    version_number: 27.0.0
    release_date: 2023/08/11
    reference_content: https://github.com/apache/druid/releases/tag/druid-27.0.0
    rationale: This version added a new OSHI system monitor (OshiSysMonitor) to replace SysMonitor. The new monitor has a wider support for different machine architectures including ARM instances.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: There are no release notes available for the Linux/ARM64. Druid seems platform-independent. The first release after the incubation phase, i.e. 0.17.0, is successfully tested on the Neoverse N1 via tar and Druid website can be accessed with release 0.17.0.
---
