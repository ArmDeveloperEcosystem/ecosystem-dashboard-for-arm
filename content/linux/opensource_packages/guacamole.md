---
name: Guacamole
category: Miscellaneous
description: Guacamole is a clientless remote desktop gateway that supports standard protocols like RDP, VNC, and SSH, allowing users to access their desktops through a web browser.
download_url: https://guacamole.apache.org/releases/
works_on_arm: true
supported_minimum_version:
    version_number: 0.9.14
    release_date: 2018/05/04


optional_info:
    homepage_url: https://guacamole.apache.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://guacamole.apache.org/doc/gug/installing-guacamole.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.5.5
        release_date: 2024/04/05
        reference_content: https://guacamole.apache.org/releases/1.5.5/
        rationale: The 1.5.5 release is a bugfix release that addresses bugs and regressions from 1.5.4 and earlier, including a resource leak that may affect RDP and SSH connections, and updates all dependencies to their latest compatible versions.  A display issue with Japanese characters in the guacd Docker image has been resolved. Several critical bugs affecting RDP protocol stability have been addressed, including segfaults during connection startup, resizing, and concurrency issues, as well as a double free issue and TLS socket synchronization problems. Authentication now correctly handles per-user connection concurrency limits, and a VNC password challenge issue has been resolved. On the maintenance side, the build process has been updated to support FFmpeg 5.0.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Binaries can be built from the source code.

---
