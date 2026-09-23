# Independent acceptance matrix — conversational dashboard search

Scope: natural-language discovery of packages already represented in the Linux dashboard. Catalog identity and metadata remain authoritative; KB evidence can establish relevance. No invented package records, no LLM requirement, no migration assistant or package crawler. A feature may be deployable without satisfying every arbitrary query, but every known ordinary-query defect needs a documented disposition and stakeholder acceptance.

## Product and evidence acceptance

| Area | Required check | Failure classification |
|---|---|---|
| Natural-language recall | Existing 37 scenarios, previous 46 independent examples, and 35 new grounded probes. Missing catalog-supported packages on ordinary language is a real defect, not proof of software unavailability. | Product blocker for an explicitly agreed scenario; unknown language coverage is a measured limitation. |
| Relevance of every result | Inspect all returned records for intended software role, each requested attribute, and edition identity. Required-name presence alone is insufficient. | Unrelated roles or unsupported claimed attributes are blockers. |
| Catalog truth | Every result ID exists in the generated catalog and content source; title, edition/license, category and recorded-test flag agree. URLs use the declared evidence source. | Any invented or mis-scoped identity/metadata is a blocker. |
| KB evidence | Controlled passages test attribution, negation, shared product names, conflicting roles, trusted host parsing, and edition boundaries. Evidence text must establish the fact; URL spelling alone does not. | False evidence admission is a blocker. |
| Filters and context | Typed filters, sidebar precedence, real new subject, old context, empty query, no-match and test-record caveat. No previous-query state leaking across clients. | Silent ignored constraints or cross-user state are blockers. |
| Honest limitations | Unsupported license/version/composition claims receive explicit clarification. Timeout fallback is visible and uses catalog facts. | Unsupported claim or silent error degradation is a blocker. |
| UI integration | Browser actual search, refinement, new subject, keyboard submission, status updates, original package expansion/resource links and Windows boundary. | Unusable flow or broken existing dashboard behavior is a blocker. |

## Deployment and operational acceptance

| Area | Practical check | Classification |
|---|---|---|
| Deployment configuration | Explicit allowed hosts/origin or documented same-origin proxy; static catalog root; dev/prod mode; docs exposure; no accidental global feature activation. Startup fails on invalid production configuration. | Missing safe deployable profile is a code/integration blocker. Actual approved hostname and hosting account are organization inputs. |
| Request boundaries | Actual bytes capped, including streamed bodies and absent/misleading Content-Length; malformed JSON/UTF-8/field types and excessive nested input rejected; bad Host/Origin rejected. | A bypassed body bound or unstable parser is a blocker. |
| Work admission | Request concurrency/rate limit separate from bounded KB workers; overload response defined; ordinary cached/catalog requests remain responsive under simulated slow KB load. | Unbounded work queue is a blocker. Capacity target and approved provider quota are organization inputs. |
| KB boundary | Requests do not follow arbitrary redirects; response byte cap; malformed JSON/metadata safe; hard caller deadline and bounded inflight work; clean client lifecycle. | Lost capacity, unhandled 500s, resource leaks or secret exposure are blockers. Network cancellation limits must be explicit. |
| Observability | Health/readiness have defined meaning; low-cardinality status/mode/timing signals; query text and credentials excluded from routine logs; operational errors traceable without public internals. | No actionable health/logging is a deployment blocker. Central monitoring destination and alert owner are organization inputs. |
| Static/API snapshot | Server and UI use same generated catalog; invalid/missing catalog fails startup; rollback rebuild uses a pinned artifact and feature switch. | Mismatched record set or unreviewable rollback is an integration blocker. |
| Build and dependencies | Pinned Python/Hugo dependencies; clean installs/builds; controlled unit/HTTP/JS regression CI; package vulnerability check with documented findings and assumptions. | Known exploitable runtime dependency or unreproducible build is a blocker. |
| Capacity experiment | Controlled local burst with provider latency/outage; report accepted/rejected counts, p50/p95/max latency, visible degradation and resource stability. No unsupported production throughput claim. | Failure to enforce configured limits is a blocker. One workstation benchmark cannot certify cluster capacity. |
| Release ownership | Approved service owner, KB access/quota contract, rollout/rollback and review sign-off; staging smoke using deployment config. | External release prerequisites, not something code or an agent can certify. |

## Review rules

- The 35 new wordings and assertions are fixed before the candidate is frozen. Do not disclose them to builders until the first run finishes.
- Every output row is checked against catalog identity and reviewed against its actual description/evidence; broad queries can legitimately return many packages.
- Run provider-independent admission/security/load checks separately from live-KB semantic tests to avoid interpreting network noise as product correctness.
- Freeze source hashes and catalog digest per evaluation. Report provider fallback occurrences and every failed expectation.
- Security findings are verified locally; no public endpoint load test or external probe is part of this review.
- Passing these finite tests supports a bounded readiness assessment, never "100% tested" or guaranteed correctness.
