---
name: CUDA-GDB
category: Compilers/Tools
description: CUDA-GDB is a CUDA-aware debugger that extends the GNU Debugger (GDB) to enable unified debugging of CPU and GPU code in CUDA applications running on real NVIDIA GPU hardware, supporting CUDA C/C++ and Fortran, device breakpoints, memory inspection, and JIT-compiled kernels across CUDA architectures.
download_url: https://github.com/NVIDIA/cuda-gdb/releases
works_on_arm: true
supported_minimum_version:
    version_number: 11.4
    release_date: 2022/12/03
 
 
optional_info:
    homepage_url: https://docs.nvidia.com/cuda/cuda-gdb/index.html#introduction
    support_caveats: CUDA-GDB is supported on all host platforms supported by the corresponding CUDA Toolkit release. GPU debugging is supported on all CUDA-capable GPUs supported by that CUDA release. Python-enabled cuda-gdb supports Python 3.8–3.12 via multiple builds; Python integration on Linux Aarch64 (SBSA) is available from CUDA-GDB 11.4 onward. Please refer [this](https://docs.nvidia.com/cuda/cuda-gdb/index.html#supported-platforms).
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.nvidia.com/cuda/cuda-gdb/index.html#getting-started
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://docs.nvidia.com/cuda/cuda-gdb/index.html
    release_notes__recommended_minimum:
    other_info: CUDA-GDB support for Linux Aarch64 probably predates 11.4. However, CUDA-GDB 11.4 is the first release to enable Python integration on Aarch64 SBSA systems.
 
---
