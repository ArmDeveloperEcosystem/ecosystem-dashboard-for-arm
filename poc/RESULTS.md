# Conversational package search — production candidate validation

Date: 23 September 2026. Review: [PR #1092](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/1092).
Base: upstream `main`, `e1871540f0a3e42e7588ab44b09e4796de967fd8`.

This revision closes the eight previously documented natural-language recall
misses, fixes additional independent-review findings, and supplies a deployable
API with an explicit production configuration. It has been exercised locally on
Linux Arm64 behind a certificate-verified HTTPS proxy. It is a candidate for the
team's staging and release process; the live dashboard has not been changed.

## Product changes

- English stemming and conversational framing recover ordinary paraphrases while
  preserving requested capabilities. TLS toolkits, playbooks, graph relationships,
  automatic HTTPS, timestamped measurements, OCR, geospatial formats and ZIP
  archives now find their catalog-grounded examples.
- Exact package names preserve exact identity and edition scope. Software roles
  are checked independently of related activities: a compilation tool is not
  automatically a compiler; a proxy is not automatically a web server. Combined
  requests must establish every requested role and compound attribute.
- Negated KB statements, adjacent product names and incidental protocol mentions
  do not establish capabilities. Existing filters, test metadata, citations and
  labelled provider/browser fallbacks remain available.
- Two catalog descriptions were corrected after independent verification:
  [Dragonfly](https://www.dragonflydb.io/docs) is an in-memory datastore with Redis
  and Memcached API compatibility; the linked
  [EMQTT project](https://github.com/emqx/emqtt) is a client library/CLI, distinct
  from the EMQX broker. Their source records and documentation links now agree.

All 1,177 Linux identities remain backed by existing dashboard source files.
No LLM is added. Default builds keep existing search; the production overlay is
an explicit opt-in. Windows search remains unchanged.

## Operational changes

The service now validates deployment settings, host/origin and explicit proxy
trust; enforces actual streamed body size/time, concurrency and rate limits;
rejects malformed/deep JSON; sanitizes internal errors; and exposes private
liveness/readiness with bounded provider work and lifecycle cleanup. Aggregate
status, latency, fallback and error logs omit raw queries and tokens.

Deployment artifacts include a nonroot API image with a digest-pinned Python
base, a runtime-only dependency lock, minimal build context, production Hugo
configuration, same-origin proxy route and rollout/rollback runbook. API and
static output must share the same generated catalog. The CI workflow now builds
and exercises the API image under production settings after deterministic tests.

## Verification

| Check | Result |
|---|---|
| Python intent, relevance, API, operations and KB tests | 209 passed |
| Existing repository regression suite | 113 passed |
| JavaScript interaction contracts | 8 passed |
| Main HTTP scenarios | 37/37 passed |
| Previous independent queries, including all eight earlier misses | 46/46 passed |
| New independent query set | 35/35 passed; every returned record reviewed |
| Production-profile real HTTP boundaries | 17/17 passed |
| Targeted evidence and failure probes | 9/9 passed |
| Final Linux Arm64 API container | 18/18 checks passed; nonroot, read-only, matching catalog digest |
| Final image behind certificate-verified local HTTPS proxy | 14/14 request checks + 8/8 artifact/behavior checks passed |
| Controlled 30-request burst, configured concurrency 2 | Two admitted; 28 promptly rejected with 503/Retry-After; recovery verified |
| Per-client rate protection | 200/200/429 at configured limit 2, despite forged forwarding headers |
| Runtime dependency audit | No known vulnerabilities reported in 17 pinned application packages |
| Hugo builds | Local, production overlay and default builds passed; Linux opt-in and Windows boundaries checked |
| Browser checks | Previously missed TLS and time-series requests display real packages; existing results/evidence layout preserved |
| Static checks | Ruff F rules, actionlint, whitespace and dependency consistency checks passed |

The 118 final HTTP scenarios used one frozen candidate with the live KB configured.
Seven responses used explicitly labelled catalog fallback. The largest observed
response time was 8.232 seconds. Unsupported/context-only cases may complete
without contacting the provider. These are finite scenario checks, not a statistical
accuracy benchmark or an agreed production latency objective.

The current evidence bundle is [production evaluation](evaluation/production/).
It records source hashes, request results, exact image identifiers and limitations.
Earlier `evaluation/independent/` and `live-search-*.json` files are historical
snapshots; their previously reported misses do not describe this revision.

One old main-suite expectation was corrected after independent review: the
query `Reverse proxy web servers` requires both roles. NGINX and NGINX Plus are
required; Haproxy (proxy/load balancer only in its catalog description) and
Gunicorn (web server without reverse-proxy evidence) are excluded. This strengthens
role checks and removes a mistaken expected positive; no other expectation was
weakened. The 35 new query wordings were fixed before the first candidate was
reviewed; additional negative assertions were added when manual review found
unrelated results. Every returned row in the independent 35-query sample was reviewed, not only required names.

Hugo retains existing missing-layout/IsSet warnings. Python tests retain two
upstream deprecation warnings. Dependency audit covers the pinned application
packages; it is not a full operating-system/container vulnerability scan.

## Remaining release inputs

The implementation does not create a backend host or modify production deployment
gates. Before public rollout, the deployment owner must supply the private API
host and same-origin route, verify real Arm staging TLS/CDN/CSP behavior, confirm
KB ownership/access/quota and privacy expectations, connect operational logs and
alerts, and approve the matching static/API artifacts. The selected release image
also needs the organization's normal container/OS scan and staging traffic test.

The local burst test proves configured admission and recovery behavior; it does
not establish cluster capacity or a production latency SLO. No production load
has been generated. Per-process limits require shared ingress limits when scaling.

Natural-language coverage is finite and depends on catalog/KB evidence quality.
Unknown paraphrases or absent evidence can still produce no matches. Unsupported
exclusions, specific licences, certifications and version claims receive explicit
notices. Recorded tests do not mean all tests passed; results remain capped at 50
and retain the dashboard's alphabetical table order. Passing these finite checks
is not a claim of universal accuracy or exhaustive testing.
