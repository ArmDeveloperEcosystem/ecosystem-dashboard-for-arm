---
name: XGBoost
category: Databases - Big-data
description: XGBoost is an optimized distributed gradient boosting library designed to be highly efficient, flexible and portable.
download_url: https://pypi.org/project/xgboost/#files
works_on_arm: true
supported_minimum_version:
  version_number: 1.2.1
  release_date: 2020/10/14
optional_info:
  homepage_url: https://xgboost.ai/
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: https://community.arm.com/arm-community-blogs/b/infrastructure-solutions-blog/posts/xgboost-lightgbm-aws-graviton3
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/machine-learning/reduce-amazon-sagemaker-inference-cost-with-aws-graviton/
    official_docs: https://xgboost.readthedocs.io/en/stable/
  arm_recommended_minimum_version:
    version_number: 1.6.2
    release_date: 2022/10/21
    reference_content: https://community.arm.com/arm-community-blogs/b/servers-and-cloud-computing-blog/posts/xgboost-lightgbm-aws-graviton3
    rationale: Benchmarks demonstrated that AWS Graviton3 instances outperformed both Graviton2 and x86 counterparts in XGBoost tasks, with performance gains of up to 50% on selected datasets.
optional_hidden_info:
  release_notes__supported_minimum: https://pypi.org/project/xgboost/1.2.1/#files
  release_notes__recommended_minimum: null
  other_info: PR to build wheels for ARM64 can be found [here](https://github.com/dmlc/xgboost/pull/6253)
---
