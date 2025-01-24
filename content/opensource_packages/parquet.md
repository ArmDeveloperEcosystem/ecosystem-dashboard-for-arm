---
name: Parquet
category: Data-format
description: Parquet is a columnar storage format for Hadoop; it provides efficient storage and encoding of data. Parquet-MR contains the java implementation of the Parquet format.
download_url: https://github.com/apache/parquet-mr/tags
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
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes available for Linux/ARM64. There is a PR merged to stop adding brotli-codec dependency for ARM64 builds (brotli-codec is not available for Linux/ARM64 according to the discussions in the following PR). Kindly find it [here](https://github.com/apache/parquet-mr/pull/872/files). This patch is rolled out in parquet-mr version 1.12.0. However, building still fails commonly on the Linux/ARM64 and Linux/AMD64 platforms since some of the other dependencies have been deprecated. These issues have been fixed in version 1.12.3, which has been successfully built on the Neoverse N1 based Linux/ARM64 platform.

---
