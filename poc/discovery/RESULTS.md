# PoC2 validation — 24–25 September 2026

The bounded internal implementation has passed local and native Linux Arm64
validation and independent verification of the review corrections. It is ready
for technical review. Approved live AI, actual staging-host acceptance,
stakeholder review and security disposition remain release gates. Browser
acceptance remains separate for the loopback demo; the batch has no web UI.
No runtime certification or universal correctness is claimed.

## Verified behavior

- Saved due investigations receive the first opportunity before discovery can
  consume the shared source allowance. Subsequent discovery and investigations
  remain bounded; deferred work persists. Explicit no-progress health reaches
  the production CLI, while ordinary partial batches and healthy no-work runs
  remain valid.
- GitHub source-record limits account for fetched rows across queries without
  changing page offsets. Reports distinguish fetched, examined and selected
  records; known and duplicate tail records do not inflate unseen deferrals.
- GitHub aliases share one active queue identity without deleting historical
  observations. Invalid identities previously admitted by older code are
  retained for manual review and excluded from active work. They cannot prevent
  valid investigations and report publication.
- Raw source/model text round-trips through escaped JSON. Word/CSV, SQLite scope
  display and diagnostics handle XML-invalid characters and lone surrogates.
  Existing affected history can be reported without deletion or refetching;
  invalid hyperlink destinations are displayed as plain text, never rewritten.
- Assessment coverage exposes verified artifacts, the remaining bounded
  inventory and specific unresolved evidence questions. Mixed architecture or
  component names alone do not imply a gap. Coverage flags remain separate from
  the three support statuses and their current/historical counts.

## Automated and independent validation

- Local Python suite: **346 tests passed**.
- Native Linux Arm64 suite: **346 tests passed**, with hash-locked dependencies,
  a nonroot user, read-only root filesystem and no network. Test-only temporary
  storage permits executable fixtures; the production image uses `noexec`.
- Existing root repository regression suite: **113 tests passed**, with the
  required Hugo 0.130.0 and Command Line Tools Git. No system Xcode license or
  system settings were changed.
- JavaScript renderer/link/filter/coverage/health checks: **11 passed**.
- Offline recovery drill: a real unclean child-process exit left 57,712 bytes
  of WAL before consistent SQLite backup. Restore preserved two prior observations,
  retirement and historical report bytes; pending work resumed to a third
  observation and the interrupted run remained auditable. Original state was
  unchanged. Zero live source/model calls.
- Read-only acceptance verifier: 31 regressions distinguish fresh healthy
  evidence from empty/history-only, stale, malformed or incomplete advisory
  runs. The saved eight-finding live sample passes metadata mode and correctly
  fails AI mode because AI was disabled; no production approval is inferred.
- Runtime image: two offline default-command executions passed with persistent
  SQLite/report state, private output permissions, UID 10001, read-only root,
  dropped capabilities and no-new-privileges. The runtime excludes the web
  server, test dependencies, pip and ensurepip. The identity, text and lifecycle modules
  are explicitly included in the production build context and image.
- Ruff error checks across the PoC, full lint on selected changed modules and new tests,
  JavaScript syntax and Git whitespace checks passed. The broader default lint
  configuration has pre-existing style findings outside this correction.
- Three independent reviewers verified requirements/report parity, scheduling
  and identity upgrades, and source/model text boundaries. The legacy invalid
  identity upgrade case found during verification was corrected and retested.
  Their assigned code findings are resolved; release acceptance remains separate.

## Public-source sample and report validation

A public-metadata recheck of an isolated SQLite backup checked **eight current
repository/image scopes: seven supported, zero gaps and one unknown**, using
27 requests with no collection failures. This included one new current MySQL
scope and seven refreshes. GitHub discovery fetched/examined 14 records and
queued two additional candidates for later. Four findings retained separate
coverage questions. AI was disabled: zero advisory reviews across eight findings.

MySQL now uses its current official `latest` image, which advertised Linux Arm64.
The former `mysql:5.7` finding is explicitly retired outside active opportunity
views; its original verdict, date and evidence remain in a separate archive.
All eight original observations were compared and preserved unchanged. The
retirement persists across runs, while a regression confirms that a genuine gap
in a current MySQL image would remain visible. GitHub now checks its designated
latest full release, with no fallback to an older release to produce a gap.

This is a bounded sample, not a globally representative top-software ranking.
Zero gaps is a valid result; versions and tags document the inspected evidence.
Current representative business opportunities still need stakeholder acceptance.
Two agents independently cross-reviewed selection/lifecycle and report/UI
changes; no blocking findings remain from that review.

Independent three-run synthetic validation checked current findings, retained
history, coverage parity and healthy no-work behavior. Word/CSV/JSON and the
actual UI renderer preserve statuses, dates and coverage questions consistently.
Reports do not assume older saved records have complete assessment coverage.

The final live-evidence Word render has **13 pages**, including the complete
bounded remaining inventories. Every page was visually inspected. The small
workload table and closing section remain together; no clipping, overlap or
unreadable inventory rows were found. Independent synthetic current/history
reports of eight and seven pages also passed full visual inspection.

Real Chrome interaction remains blocked locally by `ERR_BLOCKED_BY_CLIENT`.
HTTP and controlled DOM checks are useful validation, but do not constitute
interactive browser acceptance. A new attempt remains blocked; no browser
settings were changed. This affects demo acceptance, not a nonexistent batch UI.

## Security and release gates

The runtime dependency lock and pinned Debian Trixie base remain unchanged.
The dated baseline audit found no known advisories in the nine Python runtime
packages. Normal removal of unused mount/umount utilities reduced measured
HIGH occurrences from 44 to 40 and total OS occurrences from 156 to 150.
Eight distinct HIGH advisories remain; no CRITICAL or Python findings were
reported. Essential packages and package inventory are preserved. See
[deploy/SECURITY.md](deploy/SECURITY.md) for scope and residual risk; this is not a
security waiver. Keep the exact rebuilt image ID, commit label and final scan
with the release evidence.

Before rollout, complete:

1. Approved dedicated model/provider access, entitlement and data policy, followed
   by representative live AI-quality validation with adequate coverage.
2. Stakeholder review of evidence usefulness and false-positive/negative
   behavior on current scopes. Browser review applies separately to the demo UI.
3. Private staging-host storage, scheduling, monitoring, backup/restore, retention
   and operational ownership acceptance.
4. Security-owner disposition of residual image advisories.

The local UI remains loopback-only. No crawler schedule, deployment, catalog
update, external report publication or maintainer contact was performed. PoC1
PR #1092 remains separate and unchanged.

## Evidence retained locally

Production acceptance preparation is under `.poc/prod-readiness/`: recovery
drills, verifier results, security probes and final local/native image validation.
[ACCEPTANCE.md](deploy/ACCEPTANCE.md) specifies the remaining owner decisions.
Current-selection correction evidence is under `.poc/current-focus/`: local/native
logs, state migration assertions, current live report, renders and image checks.
Earlier correction evidence is under `.poc/review-fixes/`: reviewer notes,
regressions, final local/native logs, locked image builds/smoke, source hashes,
private public-source reports and rendered pages. Earlier baseline evidence is
under `.poc/production-review/` and `.poc/validation/`. Findings and private paths
are not committed as report artifacts. GitHub CI validates the submitted PR head;
the PR records that run and final image provenance.
