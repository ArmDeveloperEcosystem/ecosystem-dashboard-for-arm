---
name: InfluxDB
category: Database
description: InfluxDB is an open source time series database written in Rust, using Apache Arrow, Apache Parquet, and Apache DataFusion as its foundational building blocks.
download_url: https://github.com/influxdata/influxdb/releases
works_on_arm: true
supported_minimum_version:
  version_number: 2.0.3
  release_date: 2020/12/15
optional_info:
  homepage_url: https://docs.influxdata.com/influxdb/v2/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    official_docs: https://docs.influxdata.com/influxdb/v2/install/?t=Linux
    arm_content:
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/compute/making-your-go-workloads-up-to-20-faster-with-go-1-18-and-aws-graviton/
  arm_recommended_minimum_version:
    version_number: 3.0.0
    release_date: 2024/09/04
    reference_content: https://www.influxdata.com/blog/power-massive-time-series-workloads-with-influxdb-3.0/
    rationale: InfluxDB 3.0 introduces significant performance enhancements, including unlimited cardinality, high-speed data ingestion, real-time querying, and improved data compression.
optional_hidden_info:
  release_notes__supported_minimum: https://github.com/influxdata/influxdb/releases/tag/v2.0.3
  release_notes__recommended_minimum: null
  other_info: null
---
