---
name: Wordpress
category: Content mgmt platforms
description: WordPress is a content management system (CMS) that allows you to host and build websites.
download_url: https://wordpress.org/download/releases/
works_on_arm: true
supported_minimum_version:
    version_number: 5.9
    release_date: 2022/01/25


optional_info:
    homepage_url: https://developer.wordpress.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/wordpress/wordpress/
        partner_content: https://amperecomputing.com/tutorials/deploy-wordpress-and-mysql
        official_docs: https://developer.wordpress.org/advanced-administration/before-install/howto-install/
    arm_recommended_minimum_version:
        version_number: 6.8
        release_date: 2025/04/15
        reference_content: https://wordpress.org/news/2025/04/cecil/
        rationale: This version refines daily workflows with a redesigned Style Book that now supports Classic themes, allowing centralized control over site styles. It introduces speculative loading for near-instant page transitions and enhances security with bcrypt password hashing. Over 100 accessibility fixes improve navigation, labeling, and editor usability. Performance gets a major lift through query caching, block editor optimizations, and a new Interactivity API aiming for sub-50ms responses. This release strengthens speed, security, and customization—without requiring user intervention.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Version 5.8 and below have some issues while setting up the website. Issue has been observed on both ARM64 and AMD64 ubuntu 22.04. Hence, we have listed version 5.9 as the minimium supported, after setting up wordpress on the Neoverse N1.

---

