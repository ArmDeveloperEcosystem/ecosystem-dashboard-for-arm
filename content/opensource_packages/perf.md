---
name: perf
category: Compilers/Tools
description: Perf is a performance analyzing tool in linux. It can instrument CPU performance counters, tracepoints, kprobes, and uprobes (dynamic tracing).
download_url: http://ftp.am.debian.org/debian/pool/main/l/linux/
works_on_arm: true
supported_minimum_version:
    version_number: 4.18
    release_date: 2018/08/12


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
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info:

---

