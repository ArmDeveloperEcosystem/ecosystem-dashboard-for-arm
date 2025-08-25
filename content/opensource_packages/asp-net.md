---
name: ASP.NET
category: Web Server
description: ASP.NET is a web application framework. It is used to build dynamic websites, web applications and web services.
download_url: https://github.com/dotnet/aspnetcore/releases
works_on_arm: true
supported_minimum_version:
  version_number: v6.0.0
  release_date: 2021/11/08
optional_info:
  homepage_url: https://dotnet.microsoft.com/en-us/apps/aspnet
  support_caveats: null
  alternative_options: null
  getting_started_resources:
    arm_content: null
    partner_content:
      - display_name: Amazon AWS
        url: https://aws.amazon.com/blogs/dotnet/net-workflows-for-arm64-with-codecatalyst-part-1/
      - display_name: Microsoft Azure
        url: https://devblogs.microsoft.com/dotnet/improving-multiplatform-container-support/
    official_docs: https://learn.microsoft.com/en-us/aspnet/core/getting-started/?view=aspnetcore-8.0
  arm_recommended_minimum_version:
    version_number: 8.0.0
    release_date: 2023/10/03
    reference_content: https://devblogs.microsoft.com/dotnet/this-arm64-performance-in-dotnet-8/
    rationale: Added various conditional instruction processing optimizations, including conditional comparison, conditional increment, negation, and inversion, vector table lookup APIs, peephole optimizations, and more. Shows performance improvements of up to 50% in select cases.
optional_hidden_info:
  release_notes__supported_minimum: null
  release_notes__recommended_minimum: null
  other_info: Linux/ARM64 release notes are not available. Installation and testing are done via the [tar archive](https://github.com/dotnet/aspnetcore/releases/tag/v6.0.0).
---
