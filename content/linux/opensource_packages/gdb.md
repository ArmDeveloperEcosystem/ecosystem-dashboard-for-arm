---
name: GNU Debugger (GDB)
category: Compilers/Tools
description: GNU Debugger (GDB) is a tool for developers to track down and fix issues in their code by letting them pause and examine how their programs run. It works with multiple programming languages to simplify the debugging process.
download_url: https://www.sourceware.org/gdb/download/
works_on_arm: true
supported_minimum_version:
    version_number: 7.6
    release_date: 2013/04/26


optional_info:
    homepage_url: https://sourceware.org/gdb/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://sourceware.org/gdb/current/onlinedocs/gdb.html/Installing-GDB.html#Installing-GDB
        arm_content: https://developer.arm.com/documentation/102435/0100/Debugging-with-GDB
        partner_content:
    arm_recommended_minimum_version:
        version_number: 14.1
        release_date: 2023/12/03
        reference_content: https://www.sourceware.org/gdb/news/
        rationale: This version enhanced the Aarch64 support with the initial support for Scalable Matrix Extension (SME) and for Scalable Matrix Extension 2 (SME2), also the 'org.gnu.gdb.aarch64.pauth' Pointer Authentication feature is now deprecated in favor of the 'org.gnu.gdb.aarch64.pauth_v2' feature string.


optional_hidden_info:
    release_notes__supported_minimum: https://sourceware.org/legacy-ml/gdb-announce/2013/msg00001.html
    release_notes__recommended_minimum:
    other_info:

---
