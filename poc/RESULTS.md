# Scoped KB search — validation status

Local validation completed on **2 October 2026**. This replaces the earlier hybrid
search implementation. Historical semantic test counts and latency measurements
are not acceptance evidence for the new retrieval path.

**Ready for code review with live integration explicitly blocked.** The current
public KB contract has not been confirmed to provide dashboard/Linux filters
before top-k or the required platform/edition metadata. `ARM_KB_SCOPE_CONFIRMED`
is false by default; do not enable public search based on fixture success.

## Completed checks

| Check | Result and scope |
|---|---|
| Python search/API/client suite | 207 passed; two upstream dependency deprecation warnings |
| Actual HTTP integration | 31 of the 207 tests exercise FastAPI → KBClient → loopback KB fixture |
| JavaScript interaction suite | 15 passed, including ordering, refinements, cancellation, pin/unpin and edition-specific expansion |
| Existing repository tests | 113 passed, 78 subtests passed |
| HTTP boundaries | 17/17 expected statuses against a local service |
| Hugo builds | Local overlay, production-path overlay and normal feature-disabled build passed |
| Catalog identity | All 1,177 records agree with generated DOM identities; plus-sign URLs and same-slug editions covered |
| Source corrections | Flask, Perl and Porting Advisor partner links parse and render; Windows Rust/SQLite optional guide fields now render from the normal schema |
| Dependencies and changed Python lint | `pip check` and Ruff passed |
| Browser checks | Actual Chrome interactions verified rank order, open-source refinement without rewriting the query, correct edition details, browse reset and labelled outage/name fallback |

The browser success path used explicitly synthetic KB responses. With the scope
gate disabled, searching `Redis` displayed labelled name-only results. The
unavailable-provider scenario displayed no semantic matches. Passing fixture
checks establishes application integration, not live provider relevance, response
time, complete coverage of every edge case or cross-browser certification.

An independent reviewer checked scope validation, composite identities, caching,
URL handling, UI behavior, deployment and documentation. Findings corrected during
this review included encoded plus-sign identities, malformed URL path handling,
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
reported in use. No local container success is claimed. The PR's Arm64 CI job
builds and exercises the exact candidate image and uploads its result with the
revision metadata. Consult the current [PR checks](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/1092/checks)
for that outcome; prior green runs do not validate this revision.

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

1. Brian confirms the updated endpoint and exact request/response contract.
2. Verify scope and edition filtering before top-k, Linux/Windows isolation,
   descriptive ingestion and duplicate-edition preservation using the actual KB.
3. Run the agreed representative queries and inspect all returned rows. Measure
   dashboard processing separately from the KB client round trip; KB server-stage
   attribution requires provider instrumentation.
4. Validate the reviewed static/API revision pair behind the staging proxy,
   including limits, outage recovery, browser policy, expected load and the
   organization's release-image checks. Obtain the normal rollout approval.

The feature remains opt-in and the scope gate remains off until these dependencies
are resolved. See [deployment](deploy/README.md) for routing and rollback.
