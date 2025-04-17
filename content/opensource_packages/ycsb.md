---
name: YCSB
category: Miscellaneous
description: YCSB is a Cloud Serving Benchmark tool.
download_url: https://github.com/brianfrankcooper/YCSB/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.7.0
    release_date: 2016/02/25


optional_info:
    homepage_url: https://github.com/brianfrankcooper/YCSB
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/brianfrankcooper/YCSB#building-from-source
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes for Linux/ARM64. YCSB version 0.7.0 can be built (skipping tests) with jdk-8 via "mvn clean package -DskipTests". This command build jars for YCSB successfully. Tests for AccumuloDB and Solr fails commonly on both Linux ARM64 and AMD64 in this version. To build and test YCSB for other workload bindings, comment accumulo and solr from modules in pom.xml, also comment the dependencies for accumulodb-binding and solr-binding in distribution/pom.xml, and run "mvn clean package".

---
