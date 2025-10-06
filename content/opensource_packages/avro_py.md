---
name: Avro
category: Data-format
description: Apache Avro is a data serialization tool that enables compact, schema-based data exchange in distributed systems and applications.
download_url: https://github.com/apache/avro/releases
works_on_arm: true
supported_minimum_version:
    version_number: 1.7.3
    release_date: 2012/12/08
 
 
optional_info:
    homepage_url: https://avro.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://avro.apache.org/docs/1.12.0/getting-started-python/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.12.0
        release_date: 2024/08/05
        reference_content: https://github.com/apache/avro/releases/tag/release-1.12.0
        rationale: This version started using TravisCI for testing Apache Avro on Linux ARM64, which confirms the stablility of the software on Arm platform.
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. v1.7.3 has been successfully installed on the Neoverse N1, prior versions are failing to install.

---
