---
name: Arthas
category: Miscellaneous
description: Arthas provides troubleshooting for the production issues in the Java applications without modifying code or restarting servers.
download_url: https://github.com/alibaba/arthas/releases
works_on_arm: true
supported_minimum_version:
    version_number: 3.0.5
    release_date: 2018/11/28


optional_info:
    homepage_url: https://arthas.aliyun.com/en/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://arthas.aliyun.com/en/doc/install-detail.html
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no Linux/ARM64 specific release notes for the minimum version. Arthas can be installed via jar and can be run with java command. Mvn central has platform-independent arthas-boot.jar available from the minimum version 3.0.5, which is  tested with the java command "java -jar arthas-boot.jar -h"

---
