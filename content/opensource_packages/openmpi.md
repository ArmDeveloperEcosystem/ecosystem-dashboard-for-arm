---
name: OpenMPI
category: HPC
description: OpenMPI is a free and open-source library that supports parallel computing by enabling efficient communication between processes across different machines. It provides tools and protocols for distributed computing tasks in high-performance environments.
download_url: https://www.open-mpi.org/software/ompi/v5.0/
works_on_arm: true
supported_minimum_version:
    version_number: 1.6.5
    release_date: 2013/06/26


optional_info:
    homepage_url: https://www.open-mpi.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://docs.open-mpi.org/en/v5.0.x/installing-open-mpi/quickstart.html
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and Testing were done using "apt install openmpi-bin openmpi-common libopenmpi-dev". The minimum version of openmpi 1.6.5 corresponds to ubuntu:14.04 and 4.1.2 to ubuntu:22.04.

---
