---
name: HDFS
category: Databases - Big-data
description: HDFS is the primary distributed storage used by Hadoop applications. A HDFS cluster primarily consists of a NameNode that manages the file system metadata and DataNodes that store the actual data.
download_url:  https://hadoop.apache.org/release.html
works_on_arm: true
supported_minimum_version:
    version_number: 3.3.0
    release_date: 2020/07/14


optional_info:
    homepage_url: https://hadoop.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:  
        partner_content: 
        official_docs: https://github.com/apache/hadoop/blob/trunk/BUILDING.txt
    arm_recommended_minimum_version:
        version_number: 3.3.6
        release_date: 2023/06/23
        reference_content: https://hadoop.apache.org/release/3.3.6.html
        rationale: HDFS is a module within Hadoop source code that provides the primary data storage mechanism for the platform. This version of hadoop moved a number of HDFS-specific APIs to Hadoop Common to make it possible for certain applications that depend on HDFS semantics to run on other Hadoop compatible file systems. HDFS Router-Router Based Federation now supports storing delegation tokens on MySQL, which improves token operation through over the original Zookeeper-based implementation.

optional_hidden_info:
    release_notes__supported_minimum: https://hadoop.apache.org/docs/r3.3.0/
    release_notes__recommended_minimum:
    other_info: AArch64 tarball for hadoop version 3.3.0 can be downloaded from [here](https://archive.apache.org/dist/hadoop/common/hadoop-3.3.0/).

---
