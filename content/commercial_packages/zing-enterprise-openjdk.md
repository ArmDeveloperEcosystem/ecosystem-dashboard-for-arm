---
name: Azul Zing Builds of OpenJDK
vendor: Azul
category: Runtimes
description: Azul Zing Builds of OpenJDK (Zing) are commercial optimized builds of OpenJDK, currently marketed as Azul Platform Prime. Zing is free for evaluation but requires a commercial contract with Azul Systems for production use. Zing takes OpenJDK as its base and replaces several key components with optimized versions. The major additions are the C4 Pauseless Garbage Collector (the only generational, production tested pauseless garbage collection available for all major Java versions, including Java 8 and 11), the Falcon JIT Compiler (optimizes code for faster throughput, lower response latencies, and greater carrying capacity), the ReadyNow Warmup Optimizer (learns from previous runs of your application to bring applications to full speed as quickly as possible), and Azul Optimizer Hub (a separate component that offloads JIT compilation from your client machines and lets JVMs learn from each other to reach maximum speed as quickly as possible). Zing is a good choice for latency-sensitive applications that need to guarantee low median latency and minimum latency outliers, applications that aggressively scale up and down and need to be ready to handle traffic as soon as possible, and large fleets of JVMs running an application where the cost of infrastructure is an issue.
product_url: https://www.azul.com/products/prime/
works_on_arm: true
release_date_on_arm: 30/06/2022

optional_info:
    homepage_url: https://www.azul.com/downloads/#prime
    support_caveats:
    alternative_options:
    getting_started_resources:
        arm_content: https://www.azul.com/newsroom/azul-platform-prime-now-supports-64-bit-arm-including-aws-graviton-processors/
        vendor_announcement: https://docs.azul.com/prime/Sys-Reqs
        official_docs: https://docs.azul.com/prime/prime-quick-start-apt

optional_hidden_info:
    other_info: The support for ARM64 was added from version 22.06.0.0 which was released on June 30, 2022.

---
