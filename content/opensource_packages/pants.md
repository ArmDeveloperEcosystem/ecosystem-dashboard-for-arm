---
name: Pants
category: Compilers/Tools
description: Pants is a build system for codebases of all sizes. It has explicit dependency modeling, shared result caching, fine-grained invalidation, concurrent execution, unified interface for multiple tools and languages, extensibility and customizability via a plugin API.
download_url: https://github.com/pantsbuild/pants/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.16
    release_date: 2023/06/15


optional_info:
    homepage_url: https://www.pantsbuild.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://www.pantsbuild.org/2.22/docs/getting-started
    arm_recommended_minimum_version:
        version_number: 2.23.0.dev6
        release_date: 2024/08/08
        reference_content: https://github.com/pantsbuild/pants/releases/tag/release_2.23.0.dev6
        rationale: This version adds a new architecture field on all AWS Lambda targets and allows it to be set to either x86_64 or arm64 - then, uses both architecture and runtime to find the appropriate complete_platforms file to use.

optional_hidden_info:
    release_notes__supported_minimum: https://www.pantsbuild.org/2.21/docs/getting-started/prerequisites#linux
    release_notes__recommended_minimum:
    other_info: It is mentioned in the Linux system-specific notes that Pants 2.16 is distributed for Linux x86_64 and ARM64. Earlier versions are only distributed for Linux x86_64. Also, AArch64 wheels at Pypi are available from v2.16 onwards.

---
