# Independent engineering readiness review — 23 September 2026

**Verdict: no remaining blocking finding in the reviewed search and service boundaries. The frozen candidate is ready for controlled staging and production deployment review. This is not an assertion that a public production deployment, organizational sign-off, or arbitrary natural-language accuracy has been verified.**

The reviewer did not edit tracked implementation files or commit/push code. All checks used isolated local service instances and frozen copies of the reviewed source. The final source and catalog digests are in [manifest.json](manifest.json). Build, container, browser, repository-wide tests and release actions were performed separately by the implementing agent and belong in the aggregate results document.

## Final independent evidence

| Check | Observed result |
|---|---|
| New realistic query scenarios, initially withheld from builders | 35/35 final assertions passed |
| All-result identity and relevance review | 97 rows / 78 distinct real catalog records; no known role, edition, requested-qualifier or attribution failure remaining in this sample |
| Query execution | 32 retrieval attempts; one explicitly labeled catalog fallback; all 35 HTTP responses were 200; largest observed latency 8.232 seconds |
| Production-profile HTTP boundaries | 17/17 expected responses, including chunked oversized bodies, malformed/deep JSON, invalid UTF-8, bad Host/Origin and schema violations |
| Additional evidence and failure checks | 9/9: positive/negative KB evidence, compound attributes, protocol-role attribution, malformed provider output and an actual slow request body |
| Controlled local concurrent load | With request limit 2, 30 simultaneous calls admitted 2 and returned 503 + Retry-After for 28; KB work never exceeded 2 concurrent requests |
| Rate and recovery | Changing untrusted X-Forwarded-For did not evade a limit of 2: 200, 200, then 429; readiness remained 200; later search succeeded |
| Production exposure and logs | API docs returned 404; launcher logs contained status/timing and omitted submitted query text |

These are finite scenario counts, not statistical accuracy percentages or cluster-throughput certification. The artificial load settings were intentionally small to make admission behavior observable. The two admitted burst requests returned labeled fallback in under 0.9 seconds with a configured 0.15-second KB caller deadline; catalog processing and scheduling are additional to that KB-only deadline. The slow-body case returned 408 after 5.003 seconds.

The 35 final queries retain their original wordings and positive expectations. Review added four negative/evidence assertions after manual inspection; no original assertion was weakened. [Original cases](heldout_cases_original.json), [strengthened cases](heldout_cases.json), [full final HTTP responses](heldout-final.json) and the [all-result review](all-result-review.json) make that distinction visible. The queries are now disclosed regressions, not an unseen benchmark for future changes.

The implementing agent also reran the [main 37 scenarios](main-http-final.json), [previous 38 independent scenarios](previous38-final.json), and [previous eight recall probes](previous8-final.json) against the same frozen candidate. All passed, giving 118 passing final scenarios across the four sets. This reviewer inspected those results and verified their source hashes against the frozen manifest. The main suite's former Haproxy expectation for a combined reverse-proxy/web-server request was corrected: NGINX and NGINX Plus have both recorded roles; Haproxy and Gunicorn each lack one. The change is a documented expectation correction, not a weakened relevance requirement.

Operational boundary/load results were retained from candidate4 because the server, runtime, guard, launcher and KB-client modules are byte-identical to candidate5. Final query and controlled-evidence checks ran on candidate5. [Manifest provenance](manifest.json) records this distinction.

## Concrete findings resolved before this verdict

- Ordinary TLS, playbook, graph/time-series, OCR, geospatial and archive requests find the intended catalog packages. A live database-backup request now recognizes the backup utility role rather than requiring the utility itself to be a database.
- An exact short package name such as `R` returns the corresponding catalog identity. A Cassandra command-line `-R` mention does not establish the R package.
- Explicit web-server requests exclude a proxy-only role, while proxy and load-balancer searches retain relevant proxies. Combined reverse-proxy/web-server requests require both roles; an HTTP-only traffic-balancing requirement accepts explicit TCP-and-HTTP support. Compiler role checks do not equate compilation activity with being a compiler.
- Compound features require the whole positive phrase. Negation before and after a capability, including contractions, does not become positive support through stemming.
- A firewall command mentioning `80/tcp` does not establish TCP/HTTP load-balancing support. Properly attributed positive capability evidence is still admitted.
- Two pre-existing catalog descriptions were corrected: [Dragonfly's official documentation](https://www.dragonflydb.io/docs) identifies an in-memory datastore compatible with Redis/Memcached APIs; the linked [EMQTT repository](https://github.com/emqx/emqtt) identifies an MQTT client library and command-line tools. These factual corrections prevent SQL-database and MQTT-broker false results respectively.
- Actual request bytes, JSON structure, request lifetime, concurrent work and per-client rates are bounded. A provider URL containing an unpaired Unicode surrogate now produces a generic 503 rather than an unhandled serialization 500.

The targeted KB passages are explicitly synthetic transport fixtures, not factual claims about the projects named in them. The positive Redis fixture uses a direct catalog-identity URL because the existing ambiguity guard correctly refuses an uncurated generic article for an ambiguous product name. That fixture adjustment tested the compound-feature rule without bypassing or weakening identity protection.

## Remaining release inputs and practical limits

No public production service was deployed by this reviewer. Before public enablement, the team must supply the approved host/routing/TLS setup, trusted proxy boundary, KB access/quota and owner, monitoring/alert ownership, rollout/rollback sign-off, and a staging smoke check on the actual deployment. The upstream team should accept a representative query set and response-time objective. Local limits are per process and do not certify aggregate cluster capacity or provider quotas.

The matcher is a bounded KB-plus-catalog implementation with reviewed English vocabulary and inflection rules. Unsupported comparisons, exclusions and metadata constraints remain explicit limitations. Corpus quality and source freshness still constrain correctness; this review checked every returned row in the sample but did not independently certify all 1,177 catalog descriptions or all external evidence pages. The 50-result cap, alphabetical dashboard display and recorded-test caveat remain as documented.

The earlier eight ordinary-query misses are resolved in this candidate's reviewed families. A release decision should use the combined original-query regressions, these independent checks, container/browser evidence and stakeholder acceptance, not a claim of 100% testing.
