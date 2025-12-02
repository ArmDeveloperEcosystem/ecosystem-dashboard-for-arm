---
name: PostGIS
category: Database
description: PostGIS extends the capabilities of the PostgreSQL by adding support for indexing, storing, and querying geospatial data. It further provides features like Spatial Data Storage, Spatial Indexing, Spatial Functions, Geometry Processing, Raster Data Support, Geocoding and Reverse Geocoding, and Integration.
download_url: https://download.osgeo.org/postgis/source/
works_on_arm: true
supported_minimum_version:
    version_number: 3.3.3
    release_date: 2023/05/29


optional_info:
    homepage_url: https://postgis.net/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://postgis.net/docs/postgis_installation.html
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no release notes for Linux/ARM64. Postgis version 3.3.3 can be built from source from version 3.3.3 on Neoverse N1. Prior versions fail to build. Before building postgis, GEOS has to be built and installed from source, following [this](https://libgeos.org/usage/download/#build). Also, the following dependencies are required to be installed via apt "apt-get install -y wget vim build-essential postgresql proj-bin libproj-dev gcc make cmake software-properties-common libxml2-dev libjson-c-dev llvm gdal-bin protobuf-c-compiler libjsoncpp-dev libprotobuf-dev libprotobuf-c-dev libgdal-dev libpq-dev postgresql-server-dev-all".

---
