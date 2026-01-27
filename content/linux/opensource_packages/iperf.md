---
name: Iperf
category: Miscellaneous
description: Iperf is used to determine the maximum achievable bandwidth on IP networks. It reports the throughput, loss, and other parameters of every test performed.
download_url: https://downloads.es.net/pub/iperf/
works_on_arm: true
supported_minimum_version:
    version_number: 3.0.1
    release_date: 2014/05/14


optional_info:
    homepage_url: https://software.es.net/iperf/#
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://software.es.net/iperf/obtaining.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.16
        release_date: 2023/12/02
        reference_content: https://github.com/esnet/iperf/releases/tag/3.16
        rationale: Iperf 3.16 introduces multi-threaded support for parallel test streams, enabling better CPU core utilization and significantly improved throughput. The build system now detects OpenSSL 3, avoiding deprecated APIs while maintaining compatibility with OpenSSL 1.1.1. pthreads and C11 atomic support are now mandatory for building iperf3, marking a breaking change for developers.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no Linux/ARM64 release notes. The minimum version of iperf, i.e. 3.0.1 can be built from tar successfully on the Neoverse N1 and the installation is verified for AArch64 using "iperf3 --version" command.

---
