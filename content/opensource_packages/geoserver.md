---
name: GeoServer
category: Web Server
description: GeoServer is written in Java that allows geospatial data sharing and publishing. It supports various data formats and output services like Web Map Service (WMS), Web Feature Service (WFS) and Web Coverage Service (WCS).
download_url: https://github.com/geoserver/geoserver/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.22.0
    release_date: 2022/11/18


optional_info:
    homepage_url: https://geoserver.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://docs.geoserver.org/latest/en/user/gettingstarted/index.html
    arm_recommended_minimum_version:
        version_number: 2.27.1
        release_date: 2025/05/14
        reference_content: https://geoserver.org/announcements/vulnerability/2025/05/13/geoserver-2-27-1-released.html
        rationale: This is a stable release of GeoServer, officially recommended for production use. GeoServer 2.27.1 is made in conjunction with GeoTools 33.1, and GeoWebCache 1.27.1. This release enhanced WPS support with improved value reading from coverage positions and enforced coding standards by disallowing var, resolved issues including broken JSON legends, symbolizer URL errors, vector tile clipping, XML attribute encoding errors, GUI glitches, and feature templating failures.


optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: Linux/ARM64 release notes are not available. Installation and Testing were done using released tar files.

---
