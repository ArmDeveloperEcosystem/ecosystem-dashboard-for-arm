---
name: Computational Geometry Algorithms Library (CGAL)
category: Compilers/Tools
description: Computational Geometry Algorithms Library (CGAL) is a C++ library that provides a wide range of algorithms and data structures for computational geometry tasks.
download_url: https://github.com/CGAL/cgal/releases
works_on_arm: true
supported_minimum_version:
    version_number: 4.7
    release_date: 2015/10/19

optional_info:
    homepage_url: https://www.cgal.org/
    support_caveats: 
    alternative_options: 
    getting_started_resources:
        arm_content: 
        partner_content: 
        official_docs: https://doc.cgal.org/latest/Manual/general_intro.html
    arm_recommended_minimum_version:
        version_number: 6.0
        release_date: 2024/09/27
        reference_content: https://github.com/CGAL/cgal/releases/tag/v6.0
        rationale: CGAL 6.0 requires C++17, Boost ≥ 1.72.0, and now supports GCC ≥ 11.4, Clang ≥ 15.0.7, and Qt6 for demos. It removes GMP/MPFR as mandatory, enabling Boost.Multiprecision as an alternative. Major CMake changes drop UseCGAL.cmake. New packages include Kinetic Space Partition, Kinetic Surface Reconstruction, Basic Viewer, and Polygon Repair. Several internal types switch from Boost to C++17 types (std::variant, std::optional, std::shared_ptr). Key modules like AABB Tree, Arrangements, and Polygon Mesh Processing received API changes and new features. Numerous breaking changes and deprecations across triangulation, mesh generation, and shape detection modernize and streamline the library.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum:
    other_info: There are no release notes or binaries present for Linux/ARM64. CGAL version 4.7 is installed and tested on the Neoverse N1, using steps mentioned in the [document](https://doc.cgal.org/latest/Manual/usage.html).

---
