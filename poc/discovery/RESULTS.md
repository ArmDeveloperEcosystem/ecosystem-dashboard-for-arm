# PoC2 validation — 24 September 2026

The bounded internal implementation has passed local and native Linux Arm64
validation and independent verification of the review corrections. It is ready
for technical review. Approved live AI, actual staging-host acceptance, browser
acceptance, stakeholder review and security disposition remain release gates.
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

- Local Python suite: **265 tests passed**.
- Native Linux Arm64 suite: **265 tests passed**, with hash-locked dependencies,
  a nonroot user, read-only root filesystem and no network. Test-only temporary
  storage permits executable fixtures; the production image uses `noexec`.
- Existing root repository regression suite: **113 tests passed**, with the
  required Hugo 0.130.0 and Command Line Tools Git. No system Xcode license or
  system settings were changed.
- JavaScript renderer/link/filter/coverage/health checks: **10 passed**.
- Runtime image: two offline default-command executions passed with persistent
  SQLite/report state, private output permissions, UID 10001, read-only root,
  dropped capabilities and no-new-privileges. The runtime excludes the web
  server, test dependencies, pip and ensurepip. The two new identity/text modules
  are explicitly included in the production build context and image.
- Ruff checks, JavaScript syntax and Git whitespace checks passed.
- Three independent reviewers verified requirements/report parity, scheduling
  and identity upgrades, and source/model text boundaries. The legacy invalid
  identity upgrade case found during verification was corrected and retested.
  Their assigned code findings are resolved; release acceptance remains separate.

## Public-source sample and report validation

An isolated fresh run checked **eight selected repository/image scopes: six
supported, one scoped gap and one unknown**, using 29 metadata requests with no
collection failures. Two identities matched catalog URLs. GitHub discovery
fetched and examined 14 records and selected two repositories. Four findings had
separate coverage-review questions; these are not four additional support gaps.
AI was disabled: zero completed advisory reviews across eight eligible findings.

Six configured seeds plus two discoveries demonstrate the workflow, rather than
a globally representative top-software ranking. The deliberately selected legacy
`library/mysql:5.7` gap is tag-specific and is not evidence that current MySQL is
unsupported. Current representative business opportunities still need stakeholder
acceptance; no minimum number of gaps is promised.

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
interactive browser acceptance.

## Security and release gates

The runtime dependency lock and pinned Debian Trixie base remain unchanged.
The dated baseline audit found no known advisories in the nine Python runtime
packages. Its image scan found no critical or Python findings, with 44 high
package occurrences across eight distinct OS advisories. See
[deploy/SECURITY.md](deploy/SECURITY.md) for scope and residual risk; this is not a
security waiver. Keep the exact rebuilt image ID, commit label and final scan
with the release evidence.

Before rollout, complete:

1. Approved dedicated model/provider access, entitlement and data policy, followed
   by representative live AI-quality validation with adequate coverage.
2. Real browser acceptance and stakeholder review of evidence usefulness and
   false-positive/negative behavior on current scopes.
3. Private staging-host storage, scheduling, monitoring, backup/restore, retention
   and operational ownership acceptance.
4. Security-owner disposition of residual image advisories.

The local UI remains loopback-only. No crawler schedule, deployment, catalog
update, external report publication or maintainer contact was performed. PoC1
PR #1092 remains separate and unchanged.

## Evidence retained locally

Current correction evidence is under `.poc/review-fixes/`: reviewer notes,
regressions, final local/native logs, locked image builds/smoke, source hashes,
private public-source reports and rendered pages. Earlier baseline evidence is
under `.poc/production-review/` and `.poc/validation/`. Findings and private paths
are not committed as report artifacts. GitHub CI validates the submitted PR head;
the PR records that run and final image provenance.
