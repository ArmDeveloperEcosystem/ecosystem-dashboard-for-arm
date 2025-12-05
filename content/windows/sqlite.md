---
name: SQLite
category: Database
description: SQLite is a C-language library that implements a small, fast, self-contained, high-reliability, full-featured, SQL database engine.
download_url: https://github.com/sqlite/sqlite/tags
works_on_arm: true
supported_minimum_version:
  version_number: 3.50.3
  release_date: 2025/07/17

optional_info:
    homepage_url: https://www.sqlite.org/
    support_caveats:
    alternative_options:
arm_recommended_minimum_version:
  version_number:
  release_date:
  reference_content:
  rationale:
getting_started_resources:
  official_docs: "https://github.com/sqlite/sqlite?tab=readme-ov-file#compiling-for-windows-using-msvc"
  arm_content:
  partner_content:
optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Release notes are not available, we have used steps mentioned on [link](https://github.com/sqlite/sqlite?tab=readme-ov-file#compiling-for-unix-like-systems) for building the package. Versions released before 3.8.1 fails to build on Neoverse N1, due to Segmentation Fault.

---
