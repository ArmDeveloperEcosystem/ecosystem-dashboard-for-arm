---
name: Apache Tez
category: Miscellaneous
description: Apache Tez is a data-processing pipeline engine, where one can plug-in input, processing, and output implementations to perform arbitrary data-processing. It is envisioned as a low-level engine for higher abstractions such as Apache Hadoop Map-Reduce, Apache Pig, Apache Hive etc.
download_url: https://dlcdn.apache.org/tez/
works_on_arm: FALSE
supported_minimum_version:
    version_number:
    release_date:


optional_info:
    homepage_url: https://tez.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://tez.apache.org/install.html
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: The present latest version of Tez, i.e. 0.10.4, fails to build on Neoverse N1 to find phantomJS for Linux/ARM64. PhantomJS pre-builds aren't available for Linux/ARM64. Kindly refer [here](https://phantomjs.org/download.html).

---
