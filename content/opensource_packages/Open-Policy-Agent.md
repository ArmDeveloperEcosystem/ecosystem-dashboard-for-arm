--- 
name: Open Policy Agent
category: Security applications
description: The Open Policy Agent is an open-source, general-purpose policy engine that unifies policy enforcement across the stack.
download_url: https://github.com/open-policy-agent/opa/releases
works_on_arm: true
supported_minimum_version: 
    version_number: 0.37.0
    release_date: 2022/02/01

  
optional_info:
    homepage_url: https://www.openpolicyagent.org/
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content:
        partner_content: https://aws.amazon.com/blogs/opensource/deploying-open-policy-agent-opa-as-a-sidecar-on-amazon-elastic-container-service-amazon-ecs/
        official_docs: https://www.openpolicyagent.org/docs/latest/
    arm_recommended_minimum_version:
        version_number: 1.0.0
        release_date: 2024/12/21
        reference_content: https://github.com/open-policy-agent/opa/releases/tag/v1.0.0
        rationale: This version introduces stricter Rego syntax defaults, requiring if and contains, and disallowing duplicate/shadowed imports. It delivers major memory optimizations, cutting allocations and improving evaluation speed by 10–20%. Test suite performance was significantly boosted, with topdown and storage/disk tests running 50% and 75% faster, respectively. Additional updates include support for scientific notation, customizable Prometheus metrics, and enhanced Rego v1 compatibility.

  
optional_hidden_info:
    release_notes__supported_minimum: https://github.com/open-policy-agent/opa/releases/tag/v0.37.0
    release_notes__recommended_minimum:
    other_info:
--- 
