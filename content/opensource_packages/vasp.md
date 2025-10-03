---
name: The Vascular Fluid Structure Interaction Pipline (VaSP)
category: Miscellaneous
description: The Vascular Fluid Structure Interaction Simulation Pipeline (VaSP) is a toolkit for simulating fluid-structure interactions (FSI) in vascular systems.
download_url:
works_on_arm: FALSE
supported_minimum_version:
    version_number:
    release_date:


optional_info:
    homepage_url: https://kvslab.github.io/VaSP/index.html
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://kvslab.github.io/VaSP/installation.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: VaSP fails to build from source, and from Dockerfile, on Neoverse N1, for dependency vmtk. It seems like vmtk does not support Linux/ARM64, and there is an open [issue](https://github.com/vmtk/vmtk/issues/452) for the same.

---
