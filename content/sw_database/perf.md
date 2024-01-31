---
name: perf
category: Compilers/Tools
description: Perf can instrument CPU performance counters, tracepoints, kprobes, and uprobes (dynamic tracing).
download_url: https://packages.debian.org/bullseye/linux-perf
works_on_arm: true
version:
    supported_minimum: 4.18
    supported_minimum_date: 12/08/2018


optional_info:
    homepage_url: https://github.com/torvalds/linux/tree/master/tools/perf
    support_caveats: Perf (a part of linux kernel) is included in the linux-tools package (availble via apt), and the perf version depends on your linux kernel version (uname -r). For Ubuntu AWS instance with jammy distros, kernel version is 6.2.0-1017-aws, hence the perf version installed is 6.2.16.
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/install-guides/perf/
        partner_content:
        official_docs: https://perf.wiki.kernel.org/index.php/Main_Page
    arm_recommended_minimum_version:
        version_number:
        release_date:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info:

---

