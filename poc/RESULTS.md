# Conversational package search — validation and release status

Date: 25 September 2026. Review: [PR #1092](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/1092).
Base: upstream `main`, `e1871540f0a3e42e7588ab44b09e4796de967fd8`.

The corrected search implementation is a candidate for team acceptance and
staging. Current checks and historical deployment evidence are separated below;
neither constitutes approval for public rollout. The live dashboard is unchanged.

## What was validated

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
an explicit opt-in. Windows search remains unchanged. See the [implementation
guide](README.md) for behavior and limitations and the [deployment
runbook](deploy/README.md) for runtime limits, routing, rollout and rollback.

## 25 September latency validation

Article-to-package matching now compiles literal package-name patterns once per
catalog snapshot. Matching boundaries, identities, editions, ordering and evidence
checks retain their previous behavior. KB requests reuse a bounded HTTP connection
pool. Pool initialization remains lazy inside admitted workers; per-request
headers and rejected response cookies prevent session or credential carryover.
The transport closes only after admitted work finishes, including when the
application requests nonblocking shutdown.

**419 Python tests**, **113 repository tests** and **10 JavaScript tests** pass.
Local and production-overlay Hugo builds pass. Added cases cover literal and
Unicode name boundaries, duplicate editions, equivalence with the former resolver
on a 1,208-row catalog, actual loopback HTTP/1.1 connection reuse, request isolation,
initialization deadlines, response-size recovery and shutdown. An independent
reviewer ran 144 targeted tests plus initialization-recovery and 40 concurrent
shutdown probes, with no remaining actionable finding in this scope.

Two separate measurements compare the changes with `1076713cc`:

| Measurement | Before, median | After, median | Scope |
| --- | ---: | ---: | --- |
| Offline processing with frozen KB responses | 1.06s | 0.24s | Four queries, three repetitions each |
| Fresh search with live KB retrieval | 3.80s | 2.89s | Four queries, two repetitions per revision |
| Immediate repeat with KB responses cached | 1.12s | 0.25s | Eight repeats per revision |

The frozen-response check preserved complete responses across 42 query/filter
cases. Four captured KB payloads were available; remaining cases used controlled
empty provider responses. The live comparison ran old and new implementations
sequentially, reversing their order in the second round. It covered vector
databases, monitoring/alerting, local language-model serving and reverse-proxy web
servers. All eight paired fresh searches returned identical package IDs, and all
16 fresh calls succeeded without fallback. Fresh means the local retrieval cache
was cleared; provider caching was not controlled.

These are small local service measurements, excluding browser rendering and
production traffic. They do not establish a latency target. The observed KB
retrieval median remains about 2.45s after the change, including network/client
overhead; connection reuse alone cannot remove upstream processing time. Server
stage timings with the KB owners and approved staging measurements remain needed.
The earlier 118-case concurrent run below mixed cache hits and fallbacks and must
not be treated as the before/after performance baseline.

## 24 September correction validation

A further independent acceptance review found two defects that the earlier suites
did not cover. Supported filters/wrappers broadened an exact package-name request;
a Python/browser URL-parsing disagreement admitted an external evidence link as
trusted Arm content. Both have regression tests that failed before correction.
Exact identity is now preserved through supported filters and wrappers. Backend
and browser checks reject ambiguous authorities, credentials, controls and
unapproved destinations while retaining valid Arm HTTPS and local catalog links.

Longer cache and reverse-proxy descriptions now match through bounded role/context
normalization. This does not discard added requirements: HTTP, encryption, TLS
and packet capture still need evidence. No package-specific exceptions or LLM
were introduced. The original longer metrics collection/query request remains
empty with its recorded provider response because the requested operations lack
scoped evidence; it is not counted as a recovered positive.

Current deterministic validation: **368 Python tests**, **113 existing repository
tests**, and **10 JavaScript tests** pass. The additional Python cases comprise
41 identity/refinement, 42 URL-trust and 21 descriptive-query checks. The URL suite
includes a 40-URL matrix executed through both Python admission and the production
JavaScript controller under local and production page locations. Python tests now
also require Node for that cross-layer check.

The independent verifier froze 22 acceptance cases before inspecting the candidate
changes: the preceding commit passed 10/22; the correction passed **22/22** without
changing expectations. Another two protocol/evidence-preservation checks and 12
production-function browser URL checks passed. The verifier found no blocker in
that bounded correction scope. These are controlled cases and unchanged capture
replays, not new live-provider measurements or a universal relevance benchmark.
Local and production-overlay Hugo builds pass. Generated review evidence is
retained in the review workspace; the committed tests reproduce the corrected
contracts and CI publishes controlled reports for the candidate revision.

The candidate passed **118/118 HTTP regression scenarios** against a fresh local
API with the live KB configured (37 main, 38 earlier independent, 8 recall and 35
held-out cases). Four runners executed concurrently: 40 responses used explicitly
labelled catalog fallback, 77 used hybrid mode and one was catalog-only. These
results verify behavior under the observed provider/fallback mix, not uninterrupted
provider availability or a production latency target. Source hashes remained fixed.

Browser interaction checks confirmed that `Redis` followed by **With recorded
tests** retains only Redis and synchronizes the checkbox. The longer cache request
returns Memcached; the reverse-proxy description returns Haproxy, NGINX and NGINX
Plus. Arm KB evidence links and same-page catalog links remain visible and point
to their approved destinations. Browser automation used bounded DOM reads after
full-page snapshots timed out; it does not establish cross-browser coverage.

Known limits remain: exact display names have no automatic alias equivalence
(for example PostgreSQL versus the catalog's Postgres title); arbitrary
language/attribute follow-ups are not implemented. The inherited OpenVVC record
has an incorrect OpenCart description and requires a separate catalog correction.
Stakeholder acceptance must assess representative queries and these data/coverage
limits rather than infer broad semantic quality from test counts.

## Earlier relevance validation at `682534a8e`

A fresh technical review identified two primary-relevance defects after the
earlier checks: unit-testing requests admitted Benchmark and Vectorscan from
comparisons or build instructions, and a metrics-database request excluded
VictoriaMetrics because of its category. Both are corrected without package-name
exceptions. Testing roles require affirmative package-owned evidence. Metrics and
telemetry workloads remain required alongside any additional monitoring role;
negation and clauses about a different product cannot supply those capabilities.

At that revision, **264 Python tests passed**, including **55 new
[role/evidence regressions](tests/test_role_evidence.py)**; **113 existing repository tests** and **8 JavaScript
interaction tests** pass. The new regression file demonstrably fails on the
previous implementation for the defects it covers. Existing test expectations
were retained.

The independent reviewer froze 13 query/filter cases and eight controlled-evidence
cases before inspecting the implementation. Final review completed 43 diagnostic
executions, including unchanged provider captures and counterexamples found during
correction, with no failed specified assertions. All 31 returned rows across 13
identities were inspected. Twelve executions were observations without a complete
expected-result oracle; this total is not a relevance-accuracy score. The reviewer
found no remaining merge blocker within that scope.

Browser checks confirmed the two corrected searches, open-source follow-up and
clearing the query while preserving the selected filter. The query fixtures and
new deterministic regressions are committed; generated review evidence stays in
the review workspace. CI publishes the final revision's controlled test reports.

That runtime also passed **118/118 real HTTP scenarios** against a freshly
started API with the live KB configured: 37 main, 38 earlier independent, eight
earlier recall regressions and 35 held-out cases. Source hashes stayed fixed during
execution; these are disclosed regression queries, not unseen accuracy estimates.
The production-overlay build passed. Its Linux Arm64 image passed **18/18 smoke
checks**, and both corrected queries were exercised inside that image with
controlled KB inputs. Container runtime hashes match the independently reviewed
code. Actual Arm staging, release-image scanning and capacity validation remain
the release prerequisites below.

## Historical implementation validation

These results belong to the implementation preserved at
[`69b7eed6c`](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/commit/69b7eed6c4447ac9371b64b6946f0b21196cf998).
The cleanup at `f8735a22c` changed documentation, evaluation runner layout/output
handling and CI report retention while retaining application/test bytes. The final
relevance corrections change search logic and add tests; the historical
results below must not be interpreted as a fresh validation of the current code.

| Check | Result |
|---|---|
| Python intent, relevance, API, operations and KB tests | 209 passed |
| Existing repository regression suite | 113 passed |
| JavaScript interaction contracts | 8 passed |
| Main HTTP scenarios | 37/37 passed |
| Previous independent queries, including all eight earlier misses | 46/46 passed |
| Independent query set | 35/35 passed; every returned record reviewed |
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

The [archived evidence bundle](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/tree/69b7eed6c4447ac9371b64b6946f0b21196cf998/poc/evaluation/production)
retains source hashes, complete request results, image identifiers and limitations.
The [independent review](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/blob/69b7eed6c4447ac9371b64b6946f0b21196cf998/poc/evaluation/production/review.md)
and [TLS proxy review](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/blob/69b7eed6c4447ac9371b64b6946f0b21196cf998/poc/evaluation/production/tls-proxy-review.md)
are pinned to that immutable revision. Removing generated reports from the PR's
current tree does not remove this historical evidence from Git history.

One old main-suite expectation was corrected after independent review: the
query `Reverse proxy web servers` requires both roles. NGINX and NGINX Plus are
required; Haproxy (proxy/load balancer only in its catalog description) and
Gunicorn (web server without reverse-proxy evidence) are excluded. This strengthens
role checks and removes a mistaken expected positive; no other expectation was
weakened. The 35 independent query wordings were fixed before the first candidate was
reviewed; additional negative assertions were added when manual review found
unrelated results. Every returned row in the independent 35-query sample was reviewed, not only required names.

## Historical cleanup checks at `f8735a22c`

The 209 Python and 8 JavaScript checks pass on the unchanged application/test
bytes. The relocated runners preserve the 38, 8 and 35 case files byte-for-byte,
and the main evaluator retains all 33 scenarios plus 4 refinement cases.
Recorded HTTP responses were replayed against those assertions; the relocated
17 boundary and 9 targeted probes and controlled capacity/rate checks were also
executed locally. This verifies runner behavior without presenting historical
live-KB results as a newly collected benchmark.

Reusable cases and runners stay in [evaluation/](evaluation/). They are disclosed
regressions, not future unseen accuracy tests. New reports default to ignored
`.poc/evaluation/`; CI attaches only its controlled reports and tested revision
metadata for 30 days. The PR's checks show the final candidate's deterministic
tests and container smoke result. Preserve approved CI artifacts externally if
longer retention is required; the historical evidence links above do not expire
with CI artifacts.

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
