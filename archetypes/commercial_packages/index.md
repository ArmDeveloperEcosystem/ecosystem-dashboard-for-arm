---
name: # The short name of the package. Examples: 'Docker', 'CoreDNS', or 'Snyk Container'.
vendor: # The company name that offers this package. Examples: 'Snyk', or 'Oracle'.
category:  # The category this package belongs in. Must select a category (not the group name) from the package_category_list.yml at the top of the directory structure. Examples: 'Operating System', or 'Databases - noSQL'.
description: # One complete sentence description of what this package is, ending in a period. If it has an open source equivalent, include what makes this commercial package different.
product_url: # The URL that acts as the homepage for this product. Must start with 'https://'.
works_on_arm: # Boolean. It is 'true' if this package works on arm, and 'false' if not.
release_date_on_arm: # The date, in MM/DD/YYYY format, when this package first worked on Arm. Example: '04/21/2024'.


optional_info:
    homepage_url: # The URL that brings the reader to the package homepage to learn more high-level info about it. Must start with 'https://'.
    support_caveats: # If the package requires anything out of the ordinary to work on Arm, such as extra library installs or varying support across common Linux OSes, explain here. 
    alternative_options: # Only valid if 'works_on_arm' is false. Provide the name of one or more packages that address the same problem a developer is trying to solve.
    getting_started_resources:
        arm_content: # URL of a getting started resource that lives on an Arm digital domain such as learn.arm.com or community.arm.com. Must start with 'https://'.
        vendor_announcement: # URL of the blog / support notes from the vendor that announced Arm support. Must start with 'https://'.
        official_docs: # URL to a section of the docs that specifies installing on Arm if present, otherwise list the general 'getting started' docs.


optional_hidden_info:
    other_info: # Not displayed on the website. Use this to list comments that will make package maintenance easier.

---
