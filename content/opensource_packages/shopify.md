---
name: Shopify
category: E-commerce platforms
description: Shopify is a complete commerce platform that lets anyone start, manage, and grow a business. One can use Shopify to build an online store, manage sales, market to customers, and accept payments in digital and physical locations.
download_url: https://github.com/Shopify/cli/releases
works_on_arm: true
supported_minimum_version:
    version_number: 3.7.1
    release_date: 2022/08/15


optional_info:
    homepage_url: https://www.shopify.com/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://shopify.dev/docs/api/shopify-cli
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 3.66.0
        release_date: 2024/08/21
        reference_content: https://github.com/Shopify/cli/releases/tag/3.66.0
        rationale: In this release, the Shopify CLI has been updated to use the Arm64-optimized version of cloudflared (version 2024.8.2), instead of a generic or x86-only binary.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/Arm64 release notes are not available. Shopify-cli can be installed via npm. Successfully installed the minimum version 3.7.1 available at the GitHub releases via npm on the Neoverse N1. Shopify 2.x and below has been deprecated and Shopify has blocked app and extension commmands for all CLI 2.x users. Kindly refer [this](https://shopify.dev/changelog/cli-2-x-is-deprecated).

---
