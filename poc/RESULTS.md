# Conversational search PoC validation — 23 September 2026

Base: upstream `main`, `e1871540f0a3e42e7588ab44b09e4796de967fd8`.
Review: [PR #1092](https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/pull/1092).

This revision fixes confirmed search and evidence-attribution defects in the
local first-feature PoC. It is suitable for reviewing the implementation and its
limits; it is not a claim that general natural-language discovery is complete.
Production deployment and broader requirement acceptance remain separate.

## What changed

- Conversational framing is interpreted separately from software requirements.
  Ordinary vector-database questions work, filter-only follow-ups retain their
  subject, and a new request such as `Only web servers` changes the subject.
- KB retrieval preserves the semantic query order. Attributed KB passages can
  establish a workload absent from a short catalog description; catalog identity
  and software-role checks still control which records can appear.
- Postgres is retained for relational queries despite its additional JSON support.
  Transfer tools and products that merely use databases are excluded from database
  role requests. Transfer-workload requests can still find transfer tools.
- Requested attributes, negation, product editions and article attribution are
  checked before admission. URL syntax is not treated as capability evidence.
  Generic requests require positive evidence for remaining concepts rather than
  a partial word match that silently drops a requirement.
- KB caller waiting is bounded at eight seconds with at most four admitted
  requests. Slow or unavailable retrieval uses the labelled catalog fallback.
- A PR workflow builds the catalog and runs offline Python and JavaScript search
  regressions. Live-provider evaluation remains separate from deterministic CI.

All 1,177 Linux catalog records keep their existing details and links. Displayed
identities come from those records. No LLM is used. Default production and
Windows search remain unchanged; the feature is enabled by local PoC config.

## Verification

| Check | Result |
|---|---|
| Existing repository regression suite, pinned Hugo 0.130.0 extended | 113 passed |
| Python intent, relevance, API and bounded-client tests | 122 passed |
| JavaScript interaction contracts | 8 passed |
| Main HTTP scenario suite | 37/37 passed |
| Independent disclosed regression queries | 36/38 met expectations; two empty-result recall misses |
| Independent additional query probes | 2/8 met expectations; six empty-result recall misses |
| Independent targeted evidence/precision checks | 10/10 passed |
| Search-only dependency lock | Fresh environment; `pip check` passed |
| Local and default production Hugo builds | Passed; Linux opt-in and Windows boundaries checked |
| Controlled slow-KB integration through the real HTTP API | Labelled catalog results returned in 8.201 seconds, before the 15-second browser deadline |
| Browser interactions | Natural question, typed refinement, subject change, JSON workload, package expansion and constraint explanation checked |
| Static checks | Ruff F rules, workflow actionlint and whitespace checks passed |

The independent review returned 108 rows representing 63 distinct, real catalog
IDs. No known precision exclusion failed in its final sample. Two disclosed
queries used labelled fallback; the eight additional probes used live KB
retrieval. Maximum observed independent HTTP response time was 7.56 seconds.
These scenario counts are not a statistical accuracy score.

Evidence: [main HTTP scenarios](evaluation/live-search-revised.json),
[independent review](evaluation/independent/review.md), and
[controlled slow-KB HTTP check](evaluation/http-deadline.json). Source hashes
bind findings to the reviewed code. The earlier `live-search-initial.json` and
`live-search-final.json` files preserve historical 20-case runs and do not
represent this revision's broader evaluation.

Hugo emits the existing missing-page-layout and IsSet warnings. The pinned Python
test dependencies emit two deprecation warnings; these checks have no test failures.

## Remaining limits

This is a conservative KB-plus-catalog baseline with reviewed capability
vocabulary. It can miss unfamiliar phrasing or requested details absent from the
retrieved evidence. Stronger precision checks intentionally prefer no match to
an unsupported capability claim. Passing regression examples does not establish
accuracy across arbitrary language, and real catalog identities alone do not
prove relevance.

The public KB corpus includes learning paths and unrelated platforms. Final
independent checks still miss eight natural-language requests, including a TLS
toolkit, configuration management with playbooks, and converting scans into text.
Several expected packages were absent from raw KB hits, while strict catalog
matching and limited inflection handling also miss valid descriptions. These
are remaining discovery gaps, not evidence that those packages are unavailable.
Broader stakeholder-query evaluation and KB-owner review of corpus coverage and
retrieval options are needed before feature acceptance or staging sign-off.

Results retain alphabetical table order and are capped at 50. Recorded tests do
not mean all tests passed. Follow-ups cover supported filters; unsupported OR,
exclusion, licence-specific, version and certification constraints are explained
rather than guessed. Timed-out KB workers keep their slots until completion;
the eight-second caller bound is not a hard network-cancellation or shutdown bound.

This loopback application is not a deployed internal service. Staging still needs
approved hosting/access, KB ownership and quotas, operational monitoring and
broader relevance acceptance. See [README.md](README.md) for setup and commands.
