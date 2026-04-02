---
name: Quartz
category: Messaging/Comms
description: Quartz is a richly featured, open source job scheduling library that can be integrated within virtually any Java application.
download_url: https://www.quartz-scheduler.org/downloads/
works_on_arm: true
supported_minimum_version:
    version_number: 2.3.1
    release_date: 2019/03/27


optional_info:
    homepage_url: http://www.quartz-scheduler.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/quartz-scheduler/quartz/blob/main/docs/quick-start-guide.adoc
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.4.0
        release_date: 2024/11/13
        reference_content: https://github.com/quartz-scheduler/quartz/releases/tag/v2.4.0
        rationale: Quartz 2.4.0 now requires Java 8+ and has migrated its build system from Maven to Gradle. Several third-party dependencies like SLF4J, Log4j, and Hikari have been upgraded. Maven POMs generated via Gradle now declare dependencies with "provided" scope for cleaner integration. The release removes the legacy TerracottaJobStore and the NativeJob class from quartz-jobs due to security risks—now relocated as example15. Example programs can be easily run using Gradle, with guidance provided in the updated examples_guide.txt.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done using released source code tar.

---
