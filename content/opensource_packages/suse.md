---
name: SUSE Linux Enterprise Server (Open Source)
category: Operating System
description: SUSE Linux Enterprise Server (SLES) is a Linux-based server operating system designed for mainframes, servers, workstations and desktop computers.
download_url: https://www.suse.com/download/sles/
works_on_arm: true
supported_minimum_version:
    version_number: 12 SP2
    release_date: 2016/11/08


optional_info:
    homepage_url: https://www.suse.com/
    support_caveats: There are minimum hardware requirements to install SUSE on Arm hardware. For all details, read [this install guide from SUSE](https://documentation.suse.com/sles/15-SP1/html/SLES-all/cha-aarch64.html). SUSE SLES is built on an open-source codebase, meaning its core is freely available and modifiable. However, access to official updates, patches, maintenance, and enterprise support requires a paid subscription after the initial free trial.
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://documentation.suse.com/sles/15-SP5/
    arm_recommended_minimum_version:
        version_number: 15 SP3
        release_date: 2024/11/20
        reference_content: https://www.suse.com/releasenotes/aarch64/SUSE-SLES/15-SP3/index.html
        rationale: SUSE Linux Enterprise Server for Arm 15 SP3 adds a kernel flavor 64kb, offering a page size of 64 KiB and physical/virtual address size of 52 bits. Main purpose at this time is to allow for side-by-side benchmarking for High Performance Computing, Machine Learning and other Big Data use cases. Starting from 12 SP5, official Vagrant Boxes for SUSE Linux Enterprise Server x86-64 and AArch64 using the VirtualBox and libvirt providers have been released, and continued. 15 SP3 includes driver enablement for the AWS Graviton, Graviton2 System-on-Chip (SoC) chipsets, and more. 15 SP3 kernel updates the Arm Generic Interrupt Controller (GIC) driver irq-gic-v4 to prepare for upcoming chips with GIC version 4.1.

optional_hidden_info:
    release_notes__supported_minimum: https://www.suse.com/releasenotes/aarch64/SUSE-SLES/12-SP2/index.html#Intro.New
    release_notes__recommended_minimum:
    other_info:

---
