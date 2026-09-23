# Conversational search PoC validation — 23 September 2026

Base: upstream `main`, `e1871540f0a3e42e7588ab44b09e4796de967fd8`.
Review: [PR #1092](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/1092).

This local review build implements Pareena's first-feature scope: accurate
natural-language discovery of real Linux dashboard packages. Independent review
identified corrections that were incorporated into the search and regression
checks. No deployment or public catalog changes were performed.

## What works

The Linux dashboard calls Arm KB `/search`, resolves trusted hits to its real
catalog, and supplements retrieval using catalog descriptions and reviewed
capability aliases. All 1,177 Linux records retain their original details and
resources. Stable per-file identities distinguish editions. Searches and basic
refinements update the displayed rows and filters. Displayed identities are
restricted to catalog records; no LLM or model API key is required. Default
production and Windows search remain unchanged.

## Verification

| Check | Result |
|---|---|
| Existing repository regression suite, pinned Hugo 0.130.0 extended | 113 passed |
| Python search and API tests | 22 passed |
| Search-only dependency lock | Installed in a fresh environment; `pip check` passed |
| JavaScript search interaction tests | 8 passed |
| Live KB search scenario checks | 20 of 20 passed; named positive and negative checks |
| Enabled/disabled Linux and Windows build checks | Passed; production defaults retained |
| Local-only tracking-script gates | Passed; production configuration unchanged |
| Desktop browser | Search, refinements, filters and expanded package evidence checked |
| Mobile browser, 390 × 844 | Search layout inspected; no horizontal clipping observed |
| Python static checks | No undefined names or unused imports under Ruff F rules |

The live search evaluation is saved in `evaluation/live-search-final.json`.
Its named positive and negative cases cover vector databases, model serving,
monitoring, web servers, object storage, relational databases, orchestration,
message brokers/queues, caching, package names and unverifiable requests.
These checks do **not** establish general search precision or exhaustive
edge-case coverage. `live-search-initial.json` preserves the early baseline for
comparison.

Independent review corrections include duplicate-edition identities, negative
and specific-licence constraints, incidental capability mentions, unsupported
metadata interpretations, broker/queue plurals, and preserving Kafka when its
description mentions clients. Regression checks preserve these corrections.

## Boundaries for review

- Search is a KB-plus-catalog retrieval baseline with finite vocabulary. The raw
  KB corpus includes learning paths and unrelated platforms. Catalog-only
  matches and outage fallbacks are labelled. Stakeholder query evaluation and
  KB-owner confirmation remain necessary before staging.
- Catalog identity validation prevents invented package records; it does not
  guarantee relevance for every query. Sparse descriptions and unfamiliar
  paraphrases may miss valid packages. Reviewers should supply representative
  queries and expected results.
- Results keep the existing table's alphabetical order. The backend caps
  results at 50 and asks users to refine. Recorded tests do not mean every test
  passed. Unverifiable constraints receive an explicit notice.
- Follow-up refinements cover the supported filter interactions. The PoC does
  not provide unrestricted conversational reasoning, package certification or
  migration assessment.
- This loopback application is not a deployed internal service. Staging needs
  approved hosting and access controls, KB API ownership and quotas, operational
  monitoring and deployment review. This branch does not claim production
  readiness or 100% testing.

See [README.md](README.md) for local setup, suggested review queries, KB access
configuration and test reproduction commands.
