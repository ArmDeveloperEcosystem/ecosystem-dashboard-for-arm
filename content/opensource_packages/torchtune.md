---
name: torchtune
category: AI/ML 
description: torchtune is a Native-PyTorch library for LLM fine-tuning.
download_url: https://pypi.org/project/torchtune/#history
works_on_arm: true
supported_minimum_version: 
    version_number: 0.3.0
    release_date: 2024/09/18


optional_info:
    homepage_url: https://pytorch.org/torchtune/stable/overview.html
    support_caveats: torchao must be built from source - instructions in the referenced Arm content below.
    alternative_options: 
    getting_started_resources:
        arm_content: https://learn.arm.com/learning-paths/servers-and-cloud-computing/pytorch-llama/pytorch-llama#install-pytorch-and-optimized-libraries
        partner_content: 
        official_docs: https://pytorch.org/torchtune/stable/index.html
    arm_recommended_minimum_version:
        version_number: 0.4.0
        release_date: 2024/11/14
        reference_content: https://github.com/pytorch/torchtune/releases/tag/v0.4.0
        rationale: Torchtune v0.4.0 introduces major enhancements, including full support for activation offloading, new training recipes for Llama3.2V 90B and QLoRA variants, expanded support for Qwen2.5 models, and updated documentation. Activation offloading reduces memory usage by ~24% during training (tested on Llama3 8B) with minimal performance impact (<1%) and can be enabled via two simple config flags.


optional_hidden_info:
    release_notes__supported_minimum: 
    release_notes__recommended_minimum: 
    other_info: There are no Linux/ARM64 release notes. torchtune can be installed via pip. All pypi releases have none-any wheels for torchtune.

---
