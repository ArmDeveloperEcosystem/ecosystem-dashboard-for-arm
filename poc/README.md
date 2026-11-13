# Linux dashboard natural-language search

The KB selects relevant dashboard packages. The backend joins those results to the
current Linux catalog, and the existing dashboard displays the matching rows in
KB order. No additional LLM or local semantic ranking engine is used.

**Current status: live API-to-KB integration verified; relevance acceptance is pending.**
After Brian's [endpoint PR #41](https://github.com/arm/knowledge-base-endpoint/pull/41)
deployed on 14 October 2026, dev and production passed the sampled scope and
package-identity checks. The existing adapter required no code change. All eight
live representative requests returned valid catalog records, but one missed its
expected examples and other queries included weak matches. See [RESULTS.md](RESULTS.md).
`ARM_KB_SCOPE_CONFIRMED` still defaults to `false`; it is enabled only in the
local validation process. Live integration success is not production acceptance.

An opt-in direct-browser candidate is also available below. It is not enabled in
normal website builds and is not yet accepted for deployment. The API integration
described here remains available while browser access is validated.

## Request flow

```text
Dashboard browser → Search API → Arm KB (on a cache miss)
Dashboard browser ← matching current packages ← Search API
```

The KB owns semantic retrieval, scope filtering, ranking and URL/edition
deduplication. The single Python API checks the response contract, matches hits
to current catalog records, caches candidates and applies category/recorded-test
filters. The browser displays those selected IDs; local browser filtering remains
for ordinary browsing and the labelled package-name fallback.

Only current catalog records can become results. KB titles and snippets never
create package records or override catalog descriptions. The catalog is generated
by Hugo from the same revision as the UI; its internal ID is `.File.Path`.
Canonical slugs come from the existing dashboard URL convention, not filenames.
Open-source and commercial rows remain distinct even when their slugs match.

Refinement buttons and sidebar controls rerun the **same original query** with
structured filters. A new typed query starts a new search; there is no conversation
history, repository analysis, file upload, migration assistant or MCP workflow.
An example query means whatever the KB retrieves; the app does not locally infer
extra constraints from the text. Use the explicit license control for a guaranteed
license restriction.

## KB contract

The current adapter already uses the GET request shape in Brian's PR:

```text
GET /search?q=<unchanged query>&k=50
    &doc_type=Ecosystem%20Dashboard&platform=linux
    [&edition=open-source|commercial]
```

A successful response has `results: [...]`. Every hit must contain:

```json
{
  "doc_type": "Ecosystem Dashboard",
  "platform": "linux",
  "edition": "open-source",
  "url": "https://developer.arm.com/ecosystem-dashboard/linux/?package=qdrant"
}
```

The adapter uses current `https://developer.arm.com/ecosystem-dashboard/linux`
package links, with an optional trailing slash. Legacy `arm.com/developer-hub`
KB links are no longer accepted. The URL must identify one package and contain
no fragment, credentials or ambiguous encoding.
The metadata is required even for unknown/stale packages. A wrong platform,
wrong document type, missing edition or malformed URL invalidates the entire
response; known slugs with conflicting editions are also rejected. Unknown
catalog identities are omitted with a notice. The adapter preserves provider
order and relies on the KB to return unique canonical package URL/edition pairs;
it does not repeat provider deduplication.

This contract was checked against deployed retrieval package `0.5.3`, source
[`0241f0e`](https://github.com/arm/mcp/blob/0241f0e28145684c015579d9f3a78c2b63f2cebc/arm_kb_search/search.py#L984).
Its [dashboard ingestion](https://github.com/arm/mcp/blob/0241f0e28145684c015579d9f3a78c2b63f2cebc/embedding-generation/ecosystem_dashboard.py#L282)
generates a fixed URL from platform and package slug. This canonical ingestion
and provider deduplication must remain part of the scoped integration contract.

The provider must apply scope and edition **before** selecting its top results.
The advertised deployed source revision confirms this ordering; live samples
also verified Linux isolation and distinct editions. These checks do not establish
complete ingestion or search relevance. Keep `k=50`: the live comparison found
useful monitoring packages below rank 20. No additional `product` filter is required.

## Limits and unavailable search

- At most 50 KB hits are considered. Results are not an exhaustive catalog scan.
- License uses the provider edition filter. Category and recorded-test
  filters apply locally to those candidates; matching packages outside that set
  can be missed. The UI explicitly states this limitation.
- Recorded tests mean evidence exists, not that all tests passed. Open the package
  details to inspect its results.
- Validated responses are cached for five minutes, bounded to 128 entries, keyed
  by endpoint, exact query, result limit and provider scope. Different local
  refinements can reuse the same retrieved set. Failures are not cached.
- Identical simultaneous uncached requests may each reach the KB within the
  configured concurrency bound; no request-coalescing guarantee is made.
- An unconfirmed contract, invalid metadata, provider error or deadline yields
  HTTP 503 with `mode=kb_unavailable` and no semantic results. The browser labels
  its existing package-name fallback. It does not present local discovery as KB
  semantic success.

## Run locally

### Direct browser candidate

```text
Dashboard browser → Arm KB /search
Dashboard browser ← ranked hits ← Arm KB
Browser matches current package rows, applies filters and displays results
```

The browser sends the same unchanged query and scope/edition filters. It maps
returned URL, platform and edition to the package metadata rendered by Hugo,
without downloading a model, semantic index or a second catalog. Current catalog
descriptions remain the display source; KB snippets cannot create package rows.
Category and recorded-test filters still narrow the first 50 KB candidates.

This is an alternative to the Python adapter, not an additional request layer.
The browser does not call `/api/search`. Its cache lasts five minutes and holds
at most 128 validated query/edition sets **per page session**, not across users.
Timeouts, invalid results and network/CORS failures use the existing labelled
package-name fallback. No bearer token or other service secret belongs in this
build. Request limits protecting the KB must be enforced by the KB or its gateway;
browser cancellation and caching do not provide that protection.

Preview the candidate using the same pinned Hugo version below; no Python API is
required:

```sh
hugo server --config config.toml,poc/config.local.toml,poc/config.browser.toml \
  --bind 127.0.0.1 --port 8767 --baseURL http://127.0.0.1:8767/ --disableLiveReload
```

Open `http://127.0.0.1:8767/linux/`. KB dev must allow that origin for live
semantic search to work. Do not disable browser security or use `no-cors` to get
around this requirement; an unreadable response cannot supply package results.

On 13 November 2026, live GET checks using the staging and production dashboard
origins returned HTTP 200 without `Access-Control-Allow-Origin`. These are HTTP
header checks, not successful browser end-to-end validation. Before enabling the
candidate on either site, agree direct public traffic and authentication with the
KB owner, allow the exact site origins through CORS, check the website's
`connect-src` policy, and validate real browser relevance, failures and latency.
The shared backend cache is absent; a removed network hop does not guarantee
faster searches or lower KB traffic.

The first live validation target is the dashboard staging origin
`https://d1jmgdpytvgwdc.cloudfront.net` calling
`https://knowledge-dev.armdevtechapi.com/search`, as proposed by the KB owner.
Build that candidate with `config.toml,config.cloudfront.toml,poc/config.browser.toml`.
The overlay deliberately targets KB dev; do not deploy it to the production
dashboard. A production endpoint/origin configuration follows only after staging
acceptance. This preparation provisions no service and changes no deployment
workflow. The existing default-off feature flag and API deployment configuration
remain unchanged.

### Python API integration

Use Python 3.12 and Hugo extended 0.130.0 (as pinned in CI):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r poc/requirements.lock.txt
.venv/bin/python -m poc.dev --port 8765
```

Open `http://127.0.0.1:8765/linux/`. With default settings, scoped search is
unavailable and name-based browsing remains available. The regular Hugo config
leaves the search feature disabled; the local overlay opts into the UI.

For local review against the verified production KB:

```sh
ARM_KB_SCOPE_CONFIRMED=true .venv/bin/python -m poc.dev --port 8765
```

For deterministic integration/demo testing with a **synthetic KB**:

```sh
.venv/bin/python -m poc.evaluation.fixture_kb --port 8877 --app-port 8876
```

Open `http://127.0.0.1:8876/linux/`. Try `vector databases`, `Weaviate`, `Redis`,
`Voltus`, or `fixture:provider_error`. The launcher enables scoped search
only for its loopback fixture. These canned responses validate plumbing, row
matching and failure handling; they are not evidence of live search quality.

## Reproduce validation

Build the catalog first, then run the controlled suites:

```sh
hugo --config config.toml,poc/config.local.toml --destination .poc/public
.venv/bin/python -m pytest poc/tests -q
node --test poc/tests/ui_search.test.cjs
```

`test_scoped_e2e.py` runs actual loopback HTTP between FastAPI and the fixture KB,
through the production KB client. It covers unchanged queries, provider rank,
edition isolation, absent metadata, unknown records, provider errors, deadlines,
cache separation, default-off behavior and catalog/DOM identity consistency.
Existing HTTP-boundary and client tests retain body, host/origin, concurrency,
rate, timeout, response-size, credential and URL protections. Browser interaction
checks are separate from these automated contract tests.

Configure the actual endpoint and enable the scope flag only in the validation
environment. Review the draft cases in `poc/evaluation/search_cases.json` with
the product owner, then run:

```sh
.venv/bin/python -m poc.evaluate_search \
  --base-url http://127.0.0.1:8765 \
  --environment-label 'actual scoped KB validation environment'
```

This saves complete results and client-observed timings to ignored `.poc/` output.
Inspect **all** returned packages, not just required examples. Unavailable search
fails the evaluator. Its finite examples are not an accuracy percentage, and its
latency includes the client/network path. Separate provider timings require KB
instrumentation. Earlier hybrid-search evaluation is preserved in Git history;
it is not validation of this replacement.

See [deployment](deploy/README.md) for runtime limits, release checks and rollback,
and [validation status](RESULTS.md) for the current evidence.
