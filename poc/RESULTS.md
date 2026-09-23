# Local PoC validation — 23 September 2026

Base: upstream `main`, `e1871540f0a3e42e7588ab44b09e4796de967fd8`.
Branch: `feature/pareena-search-and-arm64-gap-pocs`.

This is a local review build of Pareena's updated two-feature scope. Separate
builders implemented the dashboard integration and opportunity pipeline; an
independent reviewer checked the implementation and requested corrections before
final acceptance. No deployment, public catalog changes or maintainer outreach
was performed. The personal orchestrator is outside this branch.

## What works

**Package search:** the Linux dashboard calls Arm KB `/search`, resolves trusted
hits to its real catalog, and supplements retrieval using catalog descriptions
and reviewed capability aliases. All 1,177 Linux records retain their original
details and resources. Stable per-file identities distinguish editions. Searches
and basic refinements update the displayed rows and filters. No LLM invents
package records. Default production and Windows search remain unchanged.

**Opportunity report:** selected GitHub release inventories and Docker Hub/OCI
platform metadata produce version/artifact-scoped supported, gap or unknown
findings. Reports retain evidence, timestamps, available popularity metadata,
catalog status and next actions. SQLite retains investigation history and due
dates. An internal local page supports manual runs, filtering and report download.
No downloaded software or container is executed by the collector.

## Verification

| Check | Result |
|---|---|
| Existing repository regression suite, pinned Hugo 0.130.0 extended | 113 passed |
| New Python tests: search/API and discovery/evidence/history | 60 passed |
| JavaScript search interaction tests | 8 passed |
| Live KB search scenario checks | 20 of 20 passed; named positive and negative checks |
| Enabled/disabled Linux and Windows build checks | Passed; production defaults retained |
| Local-only tracking-script gates | Passed; production configuration unchanged |
| Desktop browser | Search, refinements, filters, expanded package evidence and report views checked |
| Mobile browser, 390 × 844 | Search and report layouts inspected; no horizontal clipping observed |
| Word rendering | Full report: 6 pages; repeat report: 4 pages; every rendered page inspected |
| Download API | Word, JSON and CSV returned 200 and matched stored files |
| Python static checks | No undefined names or unused imports under Ruff F rules |

The live search evaluation is saved in `evaluation/live-search-final.json`.
Its named positive and negative cases cover vector databases, model serving,
monitoring, web servers, object storage, relational databases, orchestration,
message brokers/queues, caching, package names and unverifiable requests.
These checks do **not** establish general search precision or exhaustive edge-case
coverage. `live-search-initial.json` preserves the early baseline for comparison.

Independent review corrections include duplicate-edition identities, negative
and specific-licence constraints, incidental capability mentions, unsupported
metadata interpretations, broker/queue plurals, and preserving Kafka when its
description mentions clients. Regression checks preserve these corrections.

## Live discovery evidence

First run: `20260923T060030Z-1281b88b`, saved under `.poc/discovery-final/`.
Eight selected scopes were investigated using 26 metadata requests, with zero
collection failures: **6 supported, 1 gap, 1 unknown**. Two matched the catalog's
recorded project links. This small configuration is a demonstration, not an
ecosystem-wide prevalence estimate or a popularity benchmark.

| Scope checked | Finding | Meaning |
|---|---|---|
| `library/alpine:latest` | Supported | Checked manifest includes Linux Arm64 |
| `library/redis:latest` | Supported | Checked manifest includes Linux Arm64 |
| ripgrep `15.2.0` | Supported | At least one Linux Arm64 release artifact identified |
| jq `1.8.2` | Supported | At least one Linux Arm64 release artifact identified |
| Meilisearch `1.54.0` | Supported | At least one Linux Arm64 release artifact identified |
| Qdrant `1.19.1` | Supported | At least one Linux Arm64 release artifact identified |
| `library/mysql:5.7` | Gap | This legacy tag's checked runtime inventory lacks Linux Arm64; not a claim about MySQL as a project |
| redis/redis `8.10.2` release-binary inventory | Unknown | Insufficient unambiguous Linux binary architecture evidence; not a claim that Redis lacks Arm support |

Repeat run: `20260923T061530Z-1349b143`. **0 fresh investigations, 8 retained
findings, 8 unchanged stored observations**, one discovery request and zero
failures. Original scope, status, evidence and check dates were preserved. The
original full Word report was unchanged. The UI shows latest known findings with
historical labels, while this run's counts remain zero. The latest Word report
contains the retained evidence rather than silently dropping earlier findings.

## Boundaries for review

- Search is a KB-plus-catalog retrieval baseline with finite vocabulary. The raw
  KB corpus includes learning paths and unrelated platforms. Catalog-only
  matches and outage fallbacks are labelled. Stakeholder query evaluation and
  KB-owner confirmation remain necessary before staging.
- Results keep the existing table's alphabetical order. The backend caps results
  at 50 and asks users to refine. Recorded tests do not mean every test passed.
- The pilot configuration caps eight candidates, 50 requests and 180 seconds;
  connector pagination, payload and per-request limits also apply. It starts
  with six configured scopes and at most two GitHub search candidates.
- The optional AI evidence adapter has controlled-response tests but is disabled
  in the live demo. An approved model configuration and live-provider evaluation
  are still required. Current live findings come from deterministic evidence
  rules; AI cannot override those classifications.
- This loopback application is not a deployed internal service. Staging needs
  approved hosting, authentication, private durable storage and operational
  monitoring. This branch does not claim production readiness or 100% testing.

See [README.md](README.md) for startup and reproduction commands and
[discovery/README.md](discovery/README.md) for evidence policy and source APIs.
