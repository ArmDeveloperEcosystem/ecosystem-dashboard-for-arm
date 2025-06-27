---
name: The Visualization Toolkit (VTK)
category: HPC
description: VTK (The Visualization Toolkit) is an open-source software system for 3D computer graphics, image processing, and visualization. It provides a comprehensive suite of tools and libraries for creating complex visualizations.
download_url: https://github.com/Kitware/VTK/tags
works_on_arm: true
supported_minimum_version:
    version_number: v9.0.0.rc1
    release_date: 2020/03/16


optional_info:
    homepage_url: https://vtk.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/Kitware/VTK/blob/master/Documentation/docs/build_instructions/build.md
    arm_recommended_minimum_version:
        version_number: 9.4.1
        release_date: 2024/11/22
        reference_content: https://docs.vtk.org/en/latest/release_details/9.4.html
        rationale: This version introduces powerful new features including vtkImplicitArray for memory-efficient data access, support for higher-order Galerkin cells via vtkCellGrid, and a revamped discrete space modeling system. The rendering engine adds OpenGL tessellation shaders, WebGPU compute support, and a new ANARI backend. Python integration is enhanced with pythonic object construction, pipeline chaining, and support for Python 3.13 wheels. New I/O readers (e.g., ERF, FDS, CGNS) and vtkHDFWriter extend file format compatibility. The compute shader API, WebAssembly improvements, and VR collaboration mode elevate cross-platform and immersive visualization. A host of performance optimizations, including improved multi-threading, reduced memory usage, and modularization, enhance usability across HPC environments. Deprecated APIs and legacy modules have been removed for modernization.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://github.com/Kitware/VTK/releases/tag/v9.0.0.rc1).


---

