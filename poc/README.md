# Linux ecosystem dashboard — local PoCs

Implements Pareena's updated two-feature proposal on a fresh checkout of `main`
(`e1871540f0a3e42e7588ab44b09e4796de967fd8`). Development branch:
`feature/pareena-search-and-arm64-gap-pocs`.

## Run locally

Prerequisites: Python 3.11+ and Hugo extended 0.130.0 (the upstream CI version,
used for the final build and regression suite). Download the extended binary for
your platform from the [Hugo 0.130.0 release](https://github.com/gohugoio/hugo/releases/tag/v0.130.0)
and put it on PATH. JavaScript tests also require Node.js with `node:test`
(validated locally with Node.js 23.11.0); Node is not needed to launch the demo.
From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r poc/requirements.txt
.venv/bin/python -m poc.dev
```

`poc/requirements.lock.txt` records the exact dependency versions used for this
validation. Install from that file to reproduce them. On this workstation, the
verified Hugo binary is at `.poc/tools/hugo-bin/hugo`; add its directory to PATH
before building or running the upstream tests.

- Dashboard: <http://127.0.0.1:8765/linux/>
- Internal report: <http://127.0.0.1:8765/internal/opportunities>
- API contract: <http://127.0.0.1:8765/api/docs>

The launcher builds Hugo and serves the static site and APIs on the same loopback
origin. Stop with Ctrl-C. Re-run after source changes. `--port 8766` selects a
free port. Local configuration disables Git-derived page dates, avoiding the
macOS Xcode licence requirement without changing Xcode settings. It does not
change production configuration. Report state stays in `.poc/discovery-final/`;
set `POC_DISCOVERY_OUTPUT` to use a separate investigation queue.

## Feature 1: natural-language package discovery

The search bar stays inside the existing Linux dashboard. Existing package
rows, support information, tests, categories, license filters and resource links
remain available. Windows retains its existing search.

Try:

1. `Open-source vector databases for Arm Linux` — Chroma, Milvus, Qdrant and Weaviate.
2. `Databases for storing embeddings` — a capability description without a package name.
3. `Monitoring and alerting tools` or `Tools to serve language models locally`.
4. Refine with **Only open source** or **With recorded tests**; edit sidebar filters.
5. `Vector databases with Apache 2.0 licenses` — explains that the specific
   licence requirement cannot be verified by this PoC.

### Retrieval and truth

The existing [Arm KB search API](https://knowledge.armdevtechapi.com/docs) is
called first. Its unfiltered corpus includes learning paths and other material,
so raw top results are not automatically suitable as dashboard results. The
local service normalizes platform/license boilerplate, resolves trusted Arm
result URLs and article titles to catalog records, and combines KB evidence with
catalog description matching and a small reviewed capability vocabulary. This
is a **hybrid retrieval baseline**, not an unrestricted conversational model or
proof that the unmodified KB endpoint meets the requirement on its own.

Every displayed identity comes from a Hugo-generated catalog using the same
package source files as the UI. Stable source-file IDs distinguish commercial
and open-source editions with identical names. Explanations expose either the KB
source or the existing catalog record; catalog-only matches are not labelled as
KB results. Recorded tests require Linux + Arm64 runner metadata, a run link and
test details; recorded does not mean all passed.

The UI keeps alphabetical catalog ordering. The backend scores candidates but
does not reorder the existing table. At most 50 matches are returned, with a
refinement notice. A KB timeout uses an explicitly labelled catalog-description
fallback; a backend outage uses clearly labelled package-name matching in the
browser. Search can return no results. Unsupported constraints receive a notice
rather than a guessed certification, licence, performance, date or version answer.

This first implementation has finite query vocabulary and conservative matching.
It can miss valid paraphrases or packages whose descriptions lack the requested
facts. Monitoring and container-orchestration queries also use catalog category
boundaries to avoid incidental mentions being mistaken for a package's role.
Evaluate more stakeholder queries before staging; no universal semantic
accuracy or full conversational reasoning is claimed. The representative checks
are executable with `python -m poc.evaluate_search` and retained under
`poc/evaluation/`; they are scenario checks, not a statistical relevance benchmark.

Configuration: `ARM_KB_SEARCH_URL` (default documented endpoint), optional
`ARM_KB_API_TOKEN` (server-side environment only). The local run currently needs
no KB token. Approved staging access, quotas, corpus freshness and dashboard-only
retrieval options still require confirmation with the KB owner.

## Feature 2: internal Linux Arm64 opportunity report

Use **Run discovery** on the internal page, or:

```sh
.venv/bin/python -m poc.discovery \
  --config poc/discovery/config.example.yaml \
  --output-dir .poc/discovery-final \
  --catalog .poc/public/poc-catalog.json
```

The initial configuration selects six repository/image scopes and discovers up
to two additional repositories from a bounded, star-ranked GitHub query. It is
not a scan of the entire ecosystem. The configured maximum is eight candidates,
50 metadata requests and 180 seconds of collection, with per-request and
pagination caps. These replace the earlier six-source 200/20/5 proposal for this
small, two-source local demonstration; they are configurable, not promised counts.

The report distinguishes **supported**, **gap** and **unknown** for exact release
artifacts/container tags. A cataloged project can still have an artifact-specific
gap. Unknown is never equated with unsupported. The demo intentionally checks the
legacy `library/mysql:5.7` tag to show how a version-specific gap differs from a
project-wide support claim. Selected upstream ownership is not independently
certified; collected evidence is authoritative for each selected repository.

SQLite retains candidates, observation history, evidence, refresh dates and run
summaries. Repeat runs skip investigations until due (seven days for supported
and gaps, one day for unknown, configurable). The UI retains old findings with
original dates and a historical label; fresh counts remain separate. Word, JSON
and CSV outputs have distinct purposes: review, complete machine-readable
traceability, and spreadsheet filtering. Reports stay internal and never mutate
the public catalog or contact maintainers.

The optional AI evidence-interpretation adapter is implemented and tested with
controlled responses. It is **disabled in the live demo**. To enable the provided
adapter, configure an approved `OPENAI_API_KEY` and `OPENAI_MODEL` server-side and
set `ai_review.enabled` in the discovery config. Do not commit secrets. AI reviews
have bounded calls/time/output; quotations and URLs must match collected evidence.
AI cannot override deterministic metadata verdicts. Live provider validation is
still required when the team's model access is available.

See [discovery/README.md](discovery/README.md) for evidence policies, connector
limits, optional AI contract, source links and persistent-state behaviour.

## Tests and review

Build the local catalog first (`python -m poc.dev`, then stop it), then:

```sh
.venv/bin/python -m pytest poc/tests -q
node --test poc/tests/ui_search.test.cjs
.venv/bin/python -m poc.evaluate_search
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

On this Mac, use the installed Command Line Tools without changing the Xcode
licence state when running the upstream suite:

```sh
PATH="$PWD/.poc/tools/hugo-bin:/Library/Developer/CommandLineTools/usr/bin:$PATH" \
DEVELOPER_DIR=/Library/Developer/CommandLineTools \
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

The live evaluator uses public KB metadata and writes dated results. Unit tests
use controlled inputs and do not establish live-provider quality. Keep evidence
and results with the tested commit; [RESULTS.md](RESULTS.md) records this run.

The frontend is opt-in: only `poc/config.local.toml` enables it. Default production
builds remain on existing search. This branch provides local reviewable PoCs;
production needs approved hosting/authentication, durable private state/storage,
monitoring, model/API ownership, broader relevance evaluation and deployment review.
No personal orchestrator is included; that remains a separate design task.
