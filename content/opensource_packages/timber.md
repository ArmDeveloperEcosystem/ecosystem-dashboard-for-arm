---
name: Timber
category: Content mgmt platforms
description: Timber accelerates the creation of fully customized WordPress themes, ensuring faster development with sustainable code practices.
download_url: https://github.com/timber/timber/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.21.0
    release_date: 2015/03/07


optional_info:
    homepage_url: https://timber.github.io/docs/v2/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://timber.github.io/docs/v2/installation/installation/
    arm_recommended_minimum_version:
        version_number: 2.0.0
        release_date: 2023/11/09
        reference_content: https://github.com/timber/timber/releases/tag/2.0.0
        rationale: Timber 2.0 marks a major architectural shift by dropping support for the WordPress plugin version and transitioning fully to a Composer-based package. This update aims to improve consistency, extensibility, and compatibility with WordPress Core and modern PHP versions. Key enhancements include a streamlined API for working with posts, terms, users, and menus, a revamped system for fetching meta values, improved Twig integration, and the introduction of Class Maps and the PostCollectionInterface for more flexible object handling. Timber 2.0 also offers better support for custom integrations and an upgraded WP-CLI interface.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Timber version 0.21.0 installs on ARM64 with PHP 8.1 version. Before this version, timber requires PHP version which are in between version 5.3.0 and version 7.0 but these versions are not supported on ARM64.
---
