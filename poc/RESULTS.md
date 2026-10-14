# Scoped KB search — validation status

Automated validation repeated on **14 October 2026**. This replaces the earlier hybrid
search implementation. Historical semantic test counts and latency measurements
are not acceptance evidence for the new retrieval path.
The automated suites and three Hugo builds were rerun on 14 October. Standalone
HTTP-boundary, source-correction, dependency/lint and browser checks in the
completed-checks table retain their 2 October evidence.

**Live integration verified; semantic acceptance remains pending.** After Brian's
[endpoint PR #41](https://github.com/arm/knowledge-base-endpoint/pull/41) deployed,
both endpoints reported API 1.2.0 / retrieval package 0.5.1. The advertised source
revision `f337da3e4864cb505e0149d2e4ed24e0b139e33f` applies scope before candidate
limits and ranking. Earlier same-day failures are superseded by the live checks
below. No backend retrieval code or result limit changed. `ARM_KB_SCOPE_CONFIRMED`
remains false by default; only the local validation process enables it.
Evidence is under `.poc/kb-integration-20261014/` and `.poc/kb-live-validation-20261014/`.
Current `main` was merged to resolve a generated-catalog conflict; the combined
catalog digest was validated without changing reviewed registry evidence.

## Completed checks

| Check | Result and scope |
|---|---|
| Python search/API/client suite | 207 passed; two upstream dependency deprecation warnings |
| Actual HTTP integration | 31 of the 207 tests exercise FastAPI → KBClient → loopback KB fixture |
| JavaScript interaction suite | 17 passed, including ordering, refinements, cancellation, pin/unpin, edition-specific expansion and unnecessary-row-movement regressions |
| Existing repository tests | 113 passed, 78 subtests passed |
| HTTP boundaries | 17/17 expected statuses against a local service |
| Hugo builds | Local overlay, production-path overlay and normal feature-disabled build passed |
| Catalog identity | All 1,178 records agree with generated DOM identities. An offline replay with deterministic candidates also verified compatibility with the pinned MCP v3.3.0 serializer; this does not validate deployed ingestion or retrieval quality. Plus-sign URLs and same-slug editions covered |
| Source corrections | Flask, Perl and Porting Advisor partner links parse and render; Windows Rust/SQLite optional guide fields now render from the normal schema |
| Dependencies and changed Python lint | `pip check` and Ruff passed |
| Browser checks | Actual Chrome interactions verified rank order, open-source refinement without rewriting the query, correct edition details, browse reset and labelled outage/name fallback |

The browser success path used explicitly synthetic KB responses. With the scope
gate disabled, searching `Redis` displayed labelled name-only results. The
unavailable-provider scenario displayed no semantic matches. Passing fixture
checks establishes application integration, not live provider relevance, response
time, complete coverage of every edge case or cross-browser certification.

## Live validation after KB deployment — 14 October 2026

| Check | Observed result |
|---|---|
| Deployed contract | Nine dev/production requests; all 112 returned hit instances had valid scope, URLs and exact catalog identities. Ansible excluded Windows/guides; Weaviate editions remained distinct |
| Existing eight-query evaluator | All eight returned HTTP 200 and valid current catalog records; seven included the expected examples. All 214 displayed row occurrences were reviewed. This is not an accuracy percentage |
| Refinements and boundaries | Cached category and recorded-test refinements preserved query and rank; positive/empty subsets, invalid requests, default-off and controlled provider failure behaved as expected |
| Live browser | Headless Chrome displayed both Weaviate editions in provider order; open-source refinement selected the exact row and synchronized the sidebar. Clearing the query retained the license filter; no JavaScript exceptions |
| Result-limit comparison | Nine requests across three queries at `k=10/20/50`. Smaller lists matched the top-50 prefixes; retain 50 because useful monitoring matches occur below rank 20 |

**Relevance needs work:** “Databases for storing embeddings” returned neither
Qdrant nor Milvus in the top 50. “Tools to serve language models locally” ranked
Crystal Language above Ollama and included unrelated build/compiler tools.
Follow-up exact-name queries found Qdrant and Milvus at rank 1, confirming both
are indexed. “vector database” found them at ranks 5 and 7; the original embeddings
phrase missed both even at `k=100`. The upstream retrieval is sensitive to wording;
the exact candidate-selection/ranking cause still needs a provider trace. These
packages were absent from the raw response, not removed by the dashboard.

The eight local HTTP requests took **0.180–2.717 seconds, median 0.252 seconds**.
A separate service check ran six uncached searches plus six cached repeats.
Uncached searches measured median 0.143 seconds inside the KB client and
0.33 milliseconds of local overhead. KB client time includes
network and provider processing; these small sequential samples have uncontrolled
upstream cache state and are not a load test or server-side attribution.

### Browser display-delay investigation

The API measurements above excluded rendering. A subsequent Chrome trace
reproduced **3.87–4.75 seconds from submit to displayed results**, including
4.30/4.72 seconds when the API responded in just 19/23 milliseconds. The UI
unconditionally moved all 1,178 main/detail row pairs before and after retrieval;
`appendChild` dominated the CPU profile.

The minimal fix skips reordering while a request is pending, moves only displaced
result/pinned pairs, and restores browse order on clear. With updated code and
tooltip components ready, the same repeated queries displayed in **78/88 milliseconds**;
initial searches took 0.85/1.71 seconds, mostly API waiting. Browser work outside
the API took approximately 56–65 milliseconds. These are local samples, not a
latency guarantee. Live rank and all 1,178 rows' browse order were preserved.
The 17-test UI suite includes regressions that fail on the previous implementation.
Traces and query contrasts are saved under `.poc/kb-diagnosis-20261014/`.

An earlier independent review checked scope validation, composite identities, caching,
URL handling, UI behavior, deployment and documentation. Findings corrected during
that review included encoded plus-sign identities, malformed URL path handling,
cache credential consistency, hidden refinement notices and a redundant deep
link that could open another edition. The UI now opens the exact row's existing
details; legacy copied package URLs still follow the dashboard's existing slug
convention and are not extended by this PoC.

## Container and CI

The updated smoke test expects explicit HTTP 503 and an empty semantic result set
when the KB is unavailable. It also verifies nonroot/read-only operation, resource
limits, origin/host/body boundaries, matching catalog digest and log privacy.
Successful retrieval uses the separate real-HTTP fixture suite.

The local Docker daemon could not start because the existing Colima VM disk was
reported in use. The [Arm64 CI run for implementation commit `9f9077085`](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/actions/runs/36976597288)
then passed all 207 Python tests, 15 UI tests and **16/16 container smoke checks**.
Its artifact records PR head `9f9077085a77540bb23c48764fa44645e743b7f0` and tested
merge `4499d1d1d77b8e7b284ab031f68db90865a80c87`. No local container success is
claimed. Consult the current [PR checks](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/1092/checks)
for any subsequent revision; prior green runs do not validate changed code.

The initial upstream test invocation hit the Mac Xcode license shim. Using the
actual Command Line Tools Git binary first in PATH resolved it; no test or
product code was changed to accommodate the environment. Hugo retains its
existing missing-page-layout warning.

## Evidence and remaining acceptance

Reproduce controlled tests using [README.md](README.md). Local evidence is kept
under ignored `.poc/`, including `scoped-search-tests.xml`,
`scoped-search-tests.log`, `scoped-ui-tests.log`,
`upstream-scoped-tests-command-line-tools.log` and `scoped-boundary-http.json`.
The representative-query evaluator correctly records unavailable results as
failures when the scope gate is disabled. CI publishes only controlled test
reports, not local credentials or arbitrary workspace files.

Before live rollout:

1. Review the relevance failures with Brian, including expected package coverage
   and weak matches ranked above relevant packages.
2. Agree representative queries and acceptable results with the product owner;
   the existing examples remain draft checks.
3. Repeat live evaluation after retrieval updates and inspect all returned rows. Measure
   dashboard processing separately from the KB client round trip; KB server-stage
   attribution requires provider instrumentation.
4. Validate the reviewed static/API revision pair behind the staging proxy,
   including limits, outage recovery, browser policy, expected load and the
   organization's release-image checks. Obtain the normal rollout approval.

The feature remains opt-in and the scope gate remains off until these dependencies
are resolved. See [deployment](deploy/README.md) for routing and rollback.
