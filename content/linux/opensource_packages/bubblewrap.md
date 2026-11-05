---
name: "bubblewrap"
category: Security applications
description: "bubblewrap is a Linux namespace sandboxing tool that constructs isolated filesystem, process, and network environments."
download_url: "https://github.com/containers/bubblewrap/releases"
works_on_arm: true
supported_minimum_version:
  version_number: "0.1.0"
  release_date: "2016/06/02"
optional_info:
  homepage_url: "https://github.com/containers/bubblewrap"
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: null
    arm_content: null
    partner_content: null
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: "https://github.com/containers/bubblewrap/releases/tag/v0.1.0"
  release_notes__recommended_minimum: null
  other_info: >-
    The v0.1.0 tag is the first upstream release and Debian's archived 0.1.0-1
    binaries include Arm64, establishing availability for the initial release:
    https://snapshot.debian.org/mr/binary/bubblewrap/0.1.0-1/binfiles . This is
    a historical compatibility floor, not a security recommendation. Runtime
    use requires Linux namespaces and a host security policy that permits the
    requested namespace operations. The smoke validates native Arm64 sandbox
    execution and isolation, not every possible application policy. SPDX
    license evidence is the upstream COPYING file at tag v0.13.0.
---
