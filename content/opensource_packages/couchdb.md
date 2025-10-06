---
name: Apache CouchDB
category: Databases - noSQL
description: Apache CouchDB is an open-source NoSQL database that uses a document-oriented data model with JSON for storage, JavaScript for map-reduce queries, and a RESTful HTTP API for communication.
download_url: https://couchdb.apache.org/#download
works_on_arm: true
supported_minimum_version:
    version_number: 3.0.0
    release_date: 2020/02/28


optional_info:
    homepage_url: https://docs.couchdb.org/en/stable/intro/index.html
    support_caveats:   Ensure an Arm64-compatible Erlang is installed when building from source. Docker is recommended for easier setup.
    alternative_options:
    getting_started_resources:
        official_docs: https://docs.couchdb.org/en/stable/install/unix.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:

optional_hidden_info:
    release_notes__supported_minimum: https://docs.couchdb.org/en/stable/whatsnew/3.0.html#version-3-0-0
    release_notes__recommended_minimum:
    other_info: Arm64 support was introduced in version 3.0.0. CouchDB can be built from source or installed using Docker or native package managers on Arm64-based Linux systems starting from this version.

---
