---
name: RocksDBjni
category: Database
description: RocksDB JNI provides Java bindings to the RocksDB C++ library, enabling Java applications to use its high-performance, embeddable key-value store.
download_url: https://mvnrepository.com/artifact/org.rocksdb/rocksdbjni
works_on_arm: true
supported_minimum_version:
    version_number: 6.2.2
    release_date: 2019/08/05


optional_info:
    homepage_url: https://github.com/facebook/rocksdb/tree/main/java
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/facebook/rocksdb/wiki/rocksjava-basics
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: No release notes for Linux/ARM64. Version 6.2.2 available at the [maven central](https://mvnrepository.com/artifact/org.rocksdb/rocksdbjni) has jar, that contains librocksdbjni-linux-aarch64.so. Prior versions only have x86_64 shared object files available. Shared object file for aarch64 can be viewed with "jar -xvf  rocksdbjni-6.2.2.jar | grep lib", and can be verified for aarch64 with "file librocksdbjni-linux-aarch64.so".

---

