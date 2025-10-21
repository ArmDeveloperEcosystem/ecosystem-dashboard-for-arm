---
name: Hbase
category: Databases - Big-data
description: Apache HBase is an open-source, distributed, versioned, non-relational database.
download_url: https://archive.apache.org/dist/hbase/
works_on_arm: true
supported_minimum_version:
  version_number: hbase-0.92.0
  release_date: 2012/01/23
optional_info:
  homepage_url: https://hbase.apache.org/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://hbase.apache.org/book.html#build.on.linux.aarch64
    arm_content:
    partner_content:
      - display_name: Ampere
        url: https://amperecomputing.com/assets/Hadoop_on_Ampere_Arm_Processors_Ref_Architecture_0_75_20231024_f5784a93f6.pdf
  arm_recommended_minimum_version:
    version_number: 2.5.11
    release_date: 2025/03/30
    reference_content: https://downloads.apache.org/hbase/2.5.11/RELEASENOTES.md
    rationale: This release updates its default Hadoop build to version 3.4.1 and adjusts Kerby dependencies to align with Hadoop versions, requiring manual overrides for 3.2.x and 3.3.x. Phoenix now uses jaxws-rt instead of jaxws-ri for better compatibility. Security is improved by removing the deprecated javax.el dependency, replaced with tomcat-jasper. A new RowCounter option allows counting delete marker types via a CLI flag. Slowlog responses can now be queried using client IP alone. Build efficiency is enhanced by running flaky tests every 12 hours and staggering nightly test jobs. Finally, hbase-webapps is no longer bundled in the default JARs, reducing build size.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: Hbase should run on any platform that runs a supported version of Java, kindly refer [here](https://hbase.apache.org/book.html#build.on.linux.aarch64).
---
