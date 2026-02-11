---
name: Live Syncing Daemon(Lsyncd)
category: DevOps
description: Lsyncd is a synchronization tool that monitors local file changes and mirrors them to remote servers in real-time.
download_url: https://github.com/lsyncd/lsyncd/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.0.6
    release_date: 2012/02/16
 
 
optional_info:
    homepage_url: https://github.com/lsyncd/lsyncd
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://github.com/lsyncd/lsyncd/blob/master/INSTALL
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 2.3.0
        release_date: 2022/06/08
        reference_content: http://github.com/lsyncd/lsyncd/releases/tag/v2.3.0
        rationale: This release introduces several new features including nix flake support, crontab integration, relative executable paths, and support for tunnel commands and batchSizeLimit. A new -onepass option allows Lsyncd to exit after an initial sync, useful for one-time operations. Important fixes include resolving a filesystem injection vulnerability in direct mode, enhanced SSH argument handling, and improved Lua version compatibility in CMake. Other improvements include better support for AWS S3 syncing, rsync exclusions, and copy_unsafe_links exposure.
 
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Release notes for Linux/Arm64 is not avialable. v2.0.6 is the first released version and has been successfully installed on the Neoverse N1.
 
---
