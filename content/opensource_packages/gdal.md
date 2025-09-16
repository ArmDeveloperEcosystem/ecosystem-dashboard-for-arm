---
name: Geospatial Data Abstraction Library (GDAL)
category: Miscellaneous
description: GDAL is an open-source library for reading, writing, and manipulating geospatial data formats, widely used in geographic information system (GIS) applications.
download_url: https://tracker.debian.org/pkg/gdal
works_on_arm: true
supported_minimum_version:
  version_number: 1.10.1
  release_date: 2014/04/05
optional_info:
  homepage_url: https://gdal.org
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Amazon AWS
        url: https://repost.aws/articles/ARJV3lAJE0TcWZMrxqpQ5D3Q/installing-python-package-geopandas-on-amazon-linux-2023-for-graviton
    official_docs: https://gdal.org/download.html#linux
  arm_recommended_minimum_version:
    version_number: 3.11.0
    release_date: 2025/05/09
    reference_content: https://github.com/OSGeo/gdal/releases/tag/v3.11.0
    rationale: GDAL 3.11.0 is a major feature release introducing the new gdal front-end CLI (RFC 104), which consolidates multiple utilities including gdal raster calc, raster resclassify, and a significantly faster gdal raster tile (3–6x boost). It also ports key Python scripts (vsi list/copy/delete/move/sync) into native CLI tools and adds driver-specific commands via gdal driver. Smart Bash autocompletion and full C/C++/Python API support are included. A notable new feature is the GDALG driver, enabling streamed, replayable vector dataset execution from CLI-style workflows, similar to a VRT format.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: Linux/ARM64 release notes are not available. Installation and testing is done via "apt-get install" using the [1.10.1](https://launchpad.net/ubuntu/+source/gdal/1.10.1+dfsg-5ubuntu1) binary on Ubuntu 14.04.
---
