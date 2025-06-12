---
name: OrientDB
category: Databases - noSQL
description: OrientDB is a multi-model noSQL database that supports multiple data models, including document, graph, key-value, and object-oriented models.
download_url: https://github.com/orientechnologies/orientdb/releases
works_on_arm: true
supported_minimum_version:
    version_number: 3.0.10
    release_date: 2018/10/25

optional_info:
    homepage_url: https://orientdb.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://orientdb.org/docs/3.2.x/gettingstarted/
    arm_recommended_minimum_version:
        version_number: 3.2.40
        release_date: 2025/05/29
        reference_content: https://github.com/orientechnologies/orientdb/releases/tag/3.2.40
        rationale: This release addresses critical issues across core, server, client, and distributed components. Most notably, it fixes a composite index bug that caused incomplete query results when multiple fields were used in conditions, and resolves a disk data leak issue related to vertex link collections. Additional updates include schema access safeguards, improved index handling in views, precise float/double casting, enhanced client logging, and better rollback behavior in distributed DDL operations.

optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://github.com/orientechnologies/orientdb/releases/tag/3.0.10).
---

