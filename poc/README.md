# Linux dashboard natural-language search

The KB selects relevant dashboard packages. The backend joins those results to the
current Linux catalog, and the existing dashboard displays the matching rows in
KB order. No additional LLM or local semantic ranking engine is used.

**Current status: local integration candidate; live scoped retrieval is blocked.**
Brian has not yet supplied the updated endpoint/filter contract. The public API
last checked on 2 October 2026 ignored the proposed scope filters. Therefore
`ARM_KB_SCOPE_CONFIRMED` defaults to `false`: the service makes no KB search call
and reports search unavailable until the contract is confirmed and verified.
Fixture tests do not establish live semantic quality or production readiness.

## Request flow

```text
User describes software → same-origin POST /api/search
  → KB /search: unchanged query + dashboard/Linux scope before top-k
  → exact join: URL package slug + platform + edition
  → deduplicate while preserving KB rank
  → apply category / recorded-test refinement to retrieved candidates
  → existing dashboard rows, descriptions, details and resource links
```

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

## Proposed KB contract — confirmation required

The current adapter uses this **provisional** request shape in fixture tests:

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

The canonical legacy `https://www.arm.com/developer-hub/ecosystem-dashboard/`
package URL is also accepted. The URL must identify one package, use an approved
HTTPS origin/path and contain no fragment, credentials or ambiguous encoding.
The metadata is required even for unknown/stale packages. A wrong platform,
wrong document type, missing edition or malformed URL invalidates the entire
response; known slugs with conflicting editions are also rejected. Unknown
catalog identities are omitted with a notice. Duplicates retain their first rank.

The provider must apply scope and edition **before** selecting its top results.
Client-side metadata checks cannot prove this happened; the KB owners must verify
it, along with ingestion completeness and distinct edition preservation. Confirm
the actual syntax with Brian, adapt the small request adapter if necessary, then
run live contract and relevance checks before enabling the flag in staging.

## Limits and unavailable search

- At most 50 KB hits are considered. Results are not an exhaustive catalog scan.
- License uses the proposed provider edition filter. Category and recorded-test
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

Use Python 3.12 and Hugo extended 0.130.0 (as pinned in CI):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r poc/requirements.lock.txt
.venv/bin/python -m poc.dev --port 8765
```

Open `http://127.0.0.1:8765/linux/`. With default settings, scoped search is
unavailable and name-based browsing remains available. The regular Hugo config
leaves the search feature disabled; the local overlay opts into the UI.

For deterministic integration/demo testing with a **synthetic KB**:

```sh
.venv/bin/python -m poc.evaluation.fixture_kb --port 8877 --app-port 8876
```

Open `http://127.0.0.1:8876/linux/`. Try `vector databases`, `Weaviate`, `Redis`,
`Voltus`, or `fixture:provider_error`. The launcher enables the proposed contract
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
through the production KB client. It covers unchanged queries, rank/deduplication,
edition isolation, absent metadata, unknown records, provider errors, deadlines,
cache separation, default-off behavior and catalog/DOM identity consistency.
Existing HTTP-boundary and client tests retain body, host/origin, concurrency,
rate, timeout, response-size, credential and URL protections. Browser interaction
checks are separate from these automated contract tests.

After Brian's contract and ingestion changes are available, configure the actual
endpoint and enable the scope flag only in the validation environment. Review the
draft cases in `poc/evaluation/search_cases.json` with the product owner, then run:

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
