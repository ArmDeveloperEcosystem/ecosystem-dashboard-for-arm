---
name: YCSB
category: Miscellaneous
description: Yahoo! Cloud Serving Benchmark (YCSB) is an open-source benchmarking framework used to evaluate the performance and scalability of NoSQL databases and key-value stores under controlled workloads.
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
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/glibc-with-lse/mongo_benchmark/
        partner_content:
        official_docs: https://github.com/brianfrankcooper/YCSB#building-from-source
    arm_recommended_minimum_version:
        version_number: 0.17.0
        release_date: 2021/06/03
        reference_content: https://github.com/brianfrankcooper/YCSB/releases/tag/0.17.0
        rationale: Version 0.17.0 is used in Arm Learning Paths and offers improved performance and compatibility for benchmarking NoSQL databases on Arm.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no official release notes confirming Linux/Arm64 support for YCSB. However, version 0.7.0 builds successfully on Arm64 using JDK 8 with the command `mvn clean package -DskipTests`.Some modules (e.g., AccumuloDB and Solr) fail tests on both Arm64 and Amd64 in this version. To build YCSB excluding these, comment out `accumulo` and `solr` modules from pom.xml, and remove their dependencies in `distribution/pom.xml`, then run the same Maven build.

---
