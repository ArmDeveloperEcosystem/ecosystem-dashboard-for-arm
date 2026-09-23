# Final local TLS proxy review

**Result: 14/14 actual HTTPS request checks and 8/8 artifact/behavior checks passed.**

The API image was run on Linux Arm64 behind an official nginx image pinned by digest. TLS validation used a generated local CA and verified the `dashboard.example` hostname; no insecure TLS option was used. Only the nginx listener was published on loopback. The API listener remained private and ran as UID/GID 10001 with a read-only filesystem, dropped capabilities and bounded CPU/memory.

The documented nginx routing fragment was used with test hostname/upstream substitutions. The test verified `/ecosystem-dashboard/api/search` rewriting to private `/api/search`, correct existing vector and JSON database packages, production-prefixed catalog evidence links, and a clearly labeled controlled KB outage. It also checked cross-origin requests, spoofed forwarding headers, oversized bodies, unsupported media types, wrong methods/hosts and limits that remained effective while incoming `X-Forwarded-For` values changed. Docs, OpenAPI, health and readiness were not publicly proxied. Backend logs contained aggregate statuses and omitted the test query text. The harness waits for private API readiness and verified-TLS proxy readiness before issuing acceptance requests.

All nine application source files read from the running image matched the frozen working candidate. `results.json` records those hashes, deployment-file hashes, exact image identifiers and the individual request results. No TLS keys, certificates, raw local configuration or absolute local paths are included in this portable evidence.

This proves the local deployment route and service protections for the tested candidate. Actual Arm staging TLS, CDN/WAF behavior, release credentials, operational monitoring and expected production traffic still require environment-specific validation and release approval. Temporary test containers/network were removed; existing resources were retained.
