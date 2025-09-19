---
name: OpenSearch Data Prepper
category: Monitoring/Observability
description: OpenSearch Data Prepper is an open-source server-side data collector that ingests, filters, enriches, transforms, and aggregates data through customizable pipelines, making it ready for analysis and visualization in OpenSearch.
download_url: https://github.com/opensearch-project/data-prepper/releases
works_on_arm: true
supported_minimum_version:
    version_number: 2.5.0
    release_date: 2023/10/11
 
 
optional_info:
    homepage_url: https://docs.opensearch.org/latest/data-prepper/
    support_caveats: The official Linux/Arm64 Docker images are not yet rolled out. However, the local images for Arm can be built with Dockerfile, since the base image was updated to support Linux/Arm64 in version 2.5.0.
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content:
        official_docs: https://github.com/opensearch-project/data-prepper/blob/main/docs/getting_started.md
    arm_recommended_minimum_version:
        version_number:
        release_date:
        reference_content:
        rationale:
 
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/opensearch-project/data-prepper/releases/tag/2.5.0
    release_notes__recommended_minimum:
    other_info:
 
---
