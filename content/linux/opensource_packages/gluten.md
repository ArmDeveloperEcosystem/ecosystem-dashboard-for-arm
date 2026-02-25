---
name: Gluten
category: AI/ML
description: Apache Gluten (Incubating) is a Spark plugin that offloads JVM-based Spark SQL execution to high-performance native engines (e.g., Velox, ClickHouse) by converting Spark plans to Substrait and executing compute-intensive operators natively while retaining Spark’s distributed control flow.
download_url: https://gluten.apache.org/downloads/
works_on_arm: true
supported_minimum_version:
    version_number: 1.1.1
    release_date: 2024/03/02
 
 
optional_info:
    homepage_url: https://apache.github.io/incubator-gluten/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://apache.github.io/incubator-gluten/get-started/Velox.html
        arm_content: https://developer.arm.com/community/arm-community-blogs/b/servers-and-cloud-computing-blog/posts/spark-sql-arm64-gluten-velox
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: The release notes for the initial Linux/Arm64 support isn't available. However, version 1.1.1 documentation mentions building Gluten with Velox backend for Aarch64. Please refer [this](https://gluten.apache.org/archives/v1.1.1/docs/velox/getting-started/). Also, the [nightly builds for Aarch64](https://nightlies.apache.org/gluten/nightly-release-jdk8/) are available from version 1.5.0 onwards.
 
---
