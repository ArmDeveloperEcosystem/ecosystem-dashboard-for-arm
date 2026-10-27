---
name: bubblewrap
category: Security applications
description: bubblewrap is a Linux namespace sandboxing tool that lets applications
  construct isolated filesystem, process, and network environments.
download_url: https://github.com/containers/bubblewrap/releases
works_on_arm: true
supported_minimum_version:
  version_number: 0.1.0
  release_date: 2016/06/02
optional_info:
  homepage_url: https://github.com/containers/bubblewrap
  support_caveats: Requires Linux namespace support and a host policy that permits
    the requested namespaces. The historical minimum is not a security recommendation;
    use a maintained release. The smoke test verifies native Arm64 sandbox execution
    and isolation, not the security of every possible application sandbox policy.
  alternative_options: null
  getting_started_resources:
    official_docs: https://github.com/containers/bubblewrap#usage
    arm_content: null
    partner_content: null
  arm_recommended_minimum_version:
    version_number: null
    release_date: null
    reference_content: null
    rationale: null
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/containers/bubblewrap/releases/tag/v0.1.0
  release_notes__recommended_minimum: null
  other_info: >-
    The annotated v0.1.0 tag explicitly identifies the first release and is dated
    2016-06-02. Debian's archived bubblewrap 0.1.0-1 binaries include arm64:
    https://snapshot.debian.org/mr/binary/bubblewrap/0.1.0-1/binfiles . The Arm64
    package was first archived on 2016-06-06; this is distribution evidence, not
    the upstream release date. License links can be symlinks; inspect the actual
    COPYING text and the selected release's licensing changes rather than treating
    GitHub NOASSERTION as evidence of a missing license.
---
