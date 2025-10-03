---
name: ClearML
category: AI/ML
description: Formally Allegro Trains, ClearML is an end-to-end MLOps and LLMOps suite allowing you to focus on developing your ML code and automation.
download_url: https://github.com/allegroai/clearml/releases
works_on_arm: true
supported_minimum_version:
    version_number: 0.9.0
    release_date: 2019/06/11


optional_info:
    homepage_url: https://github.com/allegroai/clearml/
    support_caveats:
    alternative_options:
    getting_started_resources:
        official_docs: https://clear.ml/docs/latest/docs/
        arm_content:
        partner_content:
    arm_recommended_minimum_version:
        version_number: 1.16.4
        release_date: 2024/09/17
        reference_content: https://clear.ml/blog/clearml-arm-it-just-works
        rationale: The version information isn't available in the blog. However, version 1.16.4 was the latest release at the time of posting this reference blog. ClearML successfully validated seamless compatibility with Arm-based AWS Graviton2 processors, paired with NVIDIA T4G GPUs, for running AI workloads. The team ran model training jobs on EC2 G5g instances using ClearML's orchestration tools and autoscaler, confirming out-of-the-box support with no setup issues. ClearML’s silicon-agnostic design ensures it automatically pulls the right AI frameworks at runtime, leveraging Arm CPU optimizations like Kleidi and KleidiAI for efficient execution. The platform provides full visibility into training jobs, including GPU/CPU/network stats in real time. Tests showed that Graviton-based instances offer up to 20% cost savings and 60% energy reduction compared to x86 counterparts.

optional_hidden_info:
    release_notes__supported_minimum:
    release_notes__recommended_minimum:
    other_info: There are no Linux/ARM64 release notes. The first release of miniforge, i.e. 0.9.0, works on Arm via Python support.

---
