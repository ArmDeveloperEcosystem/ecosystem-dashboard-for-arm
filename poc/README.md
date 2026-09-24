# Linux ecosystem dashboard — conversational package search

Implements Pareena's agreed first-feature scope: discover packages already in
the Linux dashboard using natural-language queries, grounded in the Arm
knowledge base and dashboard catalog. Accurate package discovery is the primary
review criterion; basic refinement and filter synchronization support it.

From an existing repository clone, check out the review branch:

```sh
gh pr checkout 1092
```

## Run locally

Prerequisites: Python 3.12 and Hugo extended 0.130.0 (the upstream CI version,
used for the final build and regression suite). Download the extended binary for
your platform from the [Hugo 0.130.0 release](https://github.com/gohugoio/hugo/releases/tag/v0.130.0)
and put it on PATH. JavaScript tests also require Node.js with `node:test`
(validated locally with Node.js 23.11.0); Node is not needed to launch the demo.
From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r poc/requirements.lock.txt
.venv/bin/python -m poc.dev
```

The lock file pins the versions used for validation. Put Hugo on PATH before
launching the demo or running repository tests.

- Dashboard: <http://127.0.0.1:8765/linux/>
- API contract: <http://127.0.0.1:8765/api/docs>

The launcher builds Hugo and serves the static site and APIs on the same loopback
origin. Stop with Ctrl-C. Re-run after source changes. `--port 8766` selects a
free port. Local configuration disables Git-derived page dates, avoiding the
macOS Xcode licence requirement without changing Xcode settings. It does not
change production configuration. Local build output stays under `.poc/public/`.
The loopback address is accessible only on the machine running the application.

## What to review

The search bar stays inside the existing Linux dashboard. Existing package
rows, support information, tests, categories, license filters and resource links
remain available. The checked catalog contains 1,177 Linux records. Windows
retains its existing search.

Try:

1. `What vector databases are available?` or `Open-source vector databases for Arm Linux`.
2. `Databases for storing embeddings` — a capability description without a package name.
3. `Monitoring and alerting tools` or `Tools to serve language models locally`.
4. Refine with **Only open source** or **With recorded tests**; edit sidebar filters.
   Then try `Only web servers` to start a new software search.
5. `Vector databases with Apache 2.0 licenses` — explains that the specific
   licence requirement cannot be verified by this PoC.
6. `Tools to run unit tests` — finds testing software; a package's own build-test
   instructions do not establish that role.
7. `A time-series database for metrics` — accepts explicit workload evidence
   across catalog categories while retaining the requested database role.

For each query, check that the returned packages are relevant and already
represented in the dashboard, their details and resource links still work, and
any limitations are clearly stated. Add representative team queries and expected
packages to the PR review. Empty results are preferable to invented records.

### Retrieval and truth

The existing [Arm KB search API](https://knowledge.armdevtechapi.com/docs) is
called first. Its unfiltered corpus includes learning paths and other material,
so raw top results are not automatically suitable as dashboard results. The
service removes conversational framing while retaining software requirements,
resolves trusted Arm result URLs and article titles to catalog records, and combines
KB evidence with catalog description matching, reviewed capability vocabulary and
English morphology normalization. Software-role checks distinguish a compiler
from a tool that merely invokes compilation. This
is a **hybrid retrieval baseline**. No LLM or model API key is required. It does
not establish that the unmodified KB endpoint meets the requirement on its own,
and it does not provide unrestricted conversational reasoning.

Every displayed identity comes from a Hugo-generated catalog using the same
package source files as the UI. Stable source-file IDs distinguish commercial
and open-source editions with identical names. Explanations expose either the KB
source or the existing catalog record; catalog-only matches are not labelled as
KB results. Recorded tests require Linux + Arm64 runner metadata, a run link and
test details; recorded does not mean all passed.

The query interpreter handles conversational framing separately from software
requirements. A filter-only follow-up reuses the previous software subject; a
new request such as `Only web servers` changes it. Unsupported alternatives,
exclusions and metadata constraints receive a clarification. Query evidence must
describe the requested software role and attributes: an article about a tool
that configures a database does not make that tool a database.

Testing requests retain the testing role after recorded-test filters are parsed.
Unit-testing specialization requires affirmative framework/runner evidence;
comparisons, dependencies and instructions to test a package's own build do not
establish it. Database/broker requests can express a metrics or telemetry workload
without belonging to the Monitoring category. The workload remains required,
including when a separate monitoring feature is requested. Evidence clauses must
attribute the capability to the returned package, with negation respected.

The UI keeps alphabetical catalog ordering. The backend scores candidates but
does not reorder the existing table. At most 50 matches are returned, with a
refinement notice. A KB timeout uses an explicitly labelled catalog-description
fallback; a backend outage uses clearly labelled package-name matching in the
browser. Search can return no results. Unsupported constraints receive a notice
rather than a guessed certification, licence, performance, date or version answer.

The KB client waits at most eight seconds for retrieval and admits at most four
concurrent requests. A slow request returns control to the catalog fallback;
its worker keeps its capacity slot until the network request finishes. Streamed
responses have time and size bounds. The service closes its client on shutdown;
the deployment supervisor supplies the final process termination deadline. An
eight-second caller limit is not a promise to forcibly cancel network I/O.

This implementation has finite query vocabulary and conservative matching.
It can miss valid paraphrases or packages whose descriptions lack the requested
facts. Generic requests require positive evidence for each remaining meaningful
concept; a partial word match cannot silently drop requirements such as live
backups or packet capture. This prioritizes avoiding unsupported matches and can
increase empty results for unfamiliar wording. Monitoring and container-orchestration queries also use catalog category
boundaries to avoid incidental mentions being mistaken for a package's role.
Continue evaluating stakeholder queries during staging; no universal semantic
accuracy or full conversational reasoning is claimed. The representative checks
are executable with `python -m poc.evaluate_search` and retained under
`poc/evaluation/`; they are scenario checks, not a statistical relevance benchmark.

Configuration: `ARM_KB_SEARCH_URL` (default documented endpoint), optional
`ARM_KB_API_TOKEN` (server-side environment only). The local run currently needs
no KB token. Approved staging access, quotas, corpus freshness and dashboard-only
retrieval options still require confirmation with the KB owner.

## Tests and review

Build the local catalog first (`python -m poc.dev`, then stop it). Controlled
unit and interaction checks do not require the live KB:

```sh
.venv/bin/python -m pytest poc/tests -q
node --test poc/tests/ui_search.test.cjs
```

The upstream repository tests additionally need PyYAML (`6.0.3` was used here).
It is not required by the search application:

```sh
.venv/bin/python -m pip install PyYAML==6.0.3
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

On macOS, if Git asks for an Xcode licence despite installed Command Line Tools,
use them for the upstream suite without changing system settings:

```sh
PATH="/Library/Developer/CommandLineTools/usr/bin:$PATH" \
DEVELOPER_DIR=/Library/Developer/CommandLineTools \
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

With the local demo running, exercise the HTTP API and configured KB:

```sh
.venv/bin/python -m poc.evaluate_search --base-url http://127.0.0.1:8765
.venv/bin/python poc/evaluation/run_cases.py
.venv/bin/python poc/evaluation/run_cases.py --cases fresh_cases.json \
  --output .poc/evaluation/fresh-http.json
.venv/bin/python poc/evaluation/run_heldout.py
```

These cover 37 main scenarios, 38 earlier independent cases, 8 earlier recall
misses, and 35 independent-review cases respectively. They are now disclosed
regressions, not a future unseen accuracy benchmark. Reports default to ignored
`.poc/evaluation/`; `--output` chooses another location. Each runner exits nonzero
on failed checks. Without `--base-url`, the main evaluator runs in process and
still uses the configured KB. Live results depend on provider state; deterministic
unit tests do not establish live-provider quality.

For controlled HTTP boundary and body-timeout probes, start a separate local
API-only listener in another terminal (keep the normal demo on port 8765):

```sh
ARM_SEARCH_PUBLIC_ORIGIN=https://dashboard.example \
ARM_SEARCH_SERVE_STATIC=false ARM_SEARCH_DOCS_ENABLED=false \
ARM_KB_SEARCH_URL=http://127.0.0.1:9 ARM_SEARCH_BODY_TIMEOUT=0.15 \
ARM_SEARCH_REQUESTS_PER_MINUTE=1000 \
.venv/bin/python -m poc.serve --port 8771
```

Then run the probes; stop that listener with Ctrl-C afterwards:

```sh
.venv/bin/python poc/evaluation/run_boundaries.py \
  --base-url http://127.0.0.1:8771 --host dashboard.example
.venv/bin/python poc/evaluation/run_targeted.py --slow-body-port 8771
.venv/bin/python poc/evaluation/run_operations.py
```

The operations runner starts and stops its own controlled services on ports
8772–8774 and writes private local logs. The boundary and operations checks use
local simulated inputs; they are not production capacity measurements. See
the [deployment runbook](deploy/README.md) for the container smoke test.

The PR workflow builds both Hugo profiles, runs Python and JavaScript tests, and
builds and probes the Linux Arm64 API image. It attaches revision metadata, JUnit,
JavaScript TAP and container-smoke reports as **30-day CI artifacts**. It does not
upload local live-provider reports or query history. Archive approved evidence
with its revision before artifact expiry. Historical review evidence and the
remaining release inputs are linked in [RESULTS.md](RESULTS.md).

## Deployment and operation

The frontend is opt-in. `poc/config.local.toml` enables the local demonstration;
`poc/deploy/config.production.toml` builds the same feature for the dashboard's
`/ecosystem-dashboard` path. Default site builds keep their existing search.

The [deployment runbook](deploy/README.md) provides an API container, same-origin
reverse-proxy configuration, runtime settings, readiness checks, rollout steps
and rollback. Build the static site and API catalog from the same revision so
returned IDs and displayed records agree. The existing static-content workflows
cannot host the Python API; the API runs behind the approved dashboard origin.

The service enforces actual streamed request-size and body-time limits, bounds
in-flight requests and per-client request rates, validates host/origin, disables
public API documentation, and emits aggregate operational events without raw
query text or tokens. Forwarded client addresses are trusted only from explicitly
configured proxy IPs/CIDRs. Limits are per process; the shared ingress must enforce
the agreed global traffic budget when replicas are added.

The runtime-only lock is `poc/requirements.runtime.lock.txt`; the full test lock
adds test tools. See [RESULTS.md](RESULTS.md) for the exact tests and remaining
release inputs. Supplying deployment artifacts does not activate the live site.
The deployment owner must confirm API hosting, same-origin routing, KB usage
limits and log/alert destinations, then complete staging acceptance and the
repository's existing review/release process.
