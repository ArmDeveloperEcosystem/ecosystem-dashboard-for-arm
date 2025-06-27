---
name: Parquet
category: Data-format
description: Parquet is a columnar storage format for Hadoop; it provides efficient storage and encoding of data. Parquet-java contains the java implementation of the Parquet format.
download_url: https://github.com/apache/parquet-java/tags
works_on_arm: true
supported_minimum_version:
    version_number: 1.12.0
    release_date: 2021/03/25


optional_info:
    homepage_url: https://parquet.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://parquet.apache.org/docs/
    arm_recommended_minimum_version:
        version_number: 1.15.0
        release_date: 2024/12/03
        reference_content: https://github.com/apache/parquet-java/releases/tag/apache-parquet-1.15.0
        rationale:  This version introduces major functional upgrades including the new Parquet Joiner v2, enhanced vector I/O handling, and extended support for filter predicates with contains and not() logic. It simplifies ParquetWriter logic, improves exception handling, and enables column statistics toggling for more efficient writes. Notably, support was added for writing unencrypted files without Hadoop, and enhancements were made to Avro schema conversion and column renaming. The release also delivers a large wave of dependency upgrades, including Jackson 2.18.1, Guava 33.2.1, Arrow 17.0.0, Thrift 0.21.0, Snappy, and Commons Lang3, ensuring compatibility and performance across modern platforms.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes available for Linux/ARM64. There is a PR merged to stop adding brotli-codec dependency for ARM64 builds (brotli-codec is not available for Linux/ARM64 according to the discussions in the following PR). Kindly find it [here](https://github.com/apache/parquet-java/pull/872/files). This patch is rolled out in parquet-java version 1.12.0. However, building still fails commonly on the Linux/ARM64 and Linux/AMD64 platforms since some of the other dependencies have been deprecated. These issues have been fixed in version 1.12.3, which has been successfully built on the Neoverse N1 based Linux/ARM64 platform.

---
