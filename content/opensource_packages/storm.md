---
name: Storm
category: Databases - Big-data
description: Apache Storm is a free and open source distributed realtime computation system.
download_url: https://github.com/apache/storm/tags
works_on_arm: true
supported_minimum_version:
  version_number: 2.2.0
  release_date: 2020/06/18
optional_info:
  homepage_url: https://storm.apache.org/
  support_caveats: openjdk-11-jdk
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Amazon AWS
        url: https://gallery.ecr.aws/docker/library/storm
    official_docs: https://github.com/apache/storm/blob/master/DEVELOPER.md
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: There are no release notes or binaries present for Linux/ARM64. Version 2.2.0 of storm is installed and tested on the Neoverse N1, using steps mentioned in [DEVELOPER.md](https://github.com/apache/storm/blob/master/DEVELOPER.md). Please ensure that you have the java-11-openjdk-arm64 available in JAVA_HOME to build storm version 2.2.0.
---
