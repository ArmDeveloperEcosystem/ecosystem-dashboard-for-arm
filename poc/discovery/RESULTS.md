# PoC2 validation — 24 September 2026

Status: the bounded internal batch implementation has passed local and native
Linux Arm64 validation and independent code review. Production packaging and an
operational runbook are included. This is ready for code review; approved live AI,
actual staging-host acceptance and stakeholder review remain deployment gates.
No package runtime certification or universal correctness is claimed.

## Scope and live findings

Base: `origin/main` at `e1871540f0a3e42e7588ab44b09e4796de967fd8`.
Branch: `feature/arm64-opportunity-report`.
The final live validation used public GitHub and Docker Hub metadata, the
read-only Linux catalog, and AI review disabled. It checked **eight selected
repository/image scopes: six supported, one scoped gap and one unknown**, using
29 metadata requests with zero collection failures. Two source identities
matched catalog URLs. All live candidate-level findings, dated popularity values,
available digests and report files remain in the internal local output directory.

The six explicit seeds and two star-ranked discoveries are a bounded sample,
not a globally exhaustive top-software list. A project can contribute both a
repository-release scope and a container-tag scope. Mutable tags remain dated.

## Repeat-run memory

A SQLite backup of the first run was used to verify repeat behavior independently
of the demonstration's initial report:

- Same configuration: selected two additional previously unseen scopes; both
  had unclear distribution evidence. Original eight findings were retained
  without rechecking. Nine metadata requests, zero collection failures.
- New discovery disabled: zero investigations and zero metadata requests; all
  ten historical findings retained with their original dates.
- Fresh status counts exclude historical observations. A gap stays in memory
  even when no public dashboard update occurs.

## Automated and independent checks

- Final local Python 3.12 run: **210 tests passed**.
- Existing repository regression suite: **113 tests passed**, using the local
  Command Line Tools Git executable because the system Xcode license is pending.
  No system license/settings were changed.
- JavaScript renderer/link/filter checks: **5 tests passed**.
- Native Linux Arm64: **210 tests passed**, with locked dependencies, a nonroot
  user, read-only root filesystem and no network during tests. Test-only `/tmp`
  permits synthetic executable fixtures; the production image smoke uses
  `noexec` temporary storage.
- Production image: **two offline default-command runs passed**, including
  durable SQLite state, private report permissions, UID 10001, read-only root,
  dropped capabilities, no-new-privileges, and exclusion of test/UI dependencies.
  The final Trixie-based runtime contains neither pip nor ensurepip. All nine
  installed runtime versions match the lock and the final test image.
- Actual cleanup script: removed its active container, handled an already-removed
  container and preserved an unrelated canary. This does not validate a real
  host's systemd integration.
- Ruff undefined/import checks, JavaScript syntax and Git whitespace checks pass.
- All eight local page/API/download routes return HTTP 200. Invalid-origin run
  requests, outside-directory downloads and private state access are tested.

Production image validated locally:
`sha256:40a71b70f8610bb2f32f002172d8ef93f7eddc6c2d10668e6cc4881c069da5b8`.
All 11 packaged Python files match the frozen validation manifest. The image is
local; it has not been published to a registry or installed on a staging host.

Builder, tester and an independent fresh-context reviewer shared findings and
retested corrections. The tester's initial 28 cases reproduced 19 failures;
all now pass, alongside two further privacy/fingerprint regressions. Fixes cover
invalid artifact sizes, explicit source privacy/identity rejection, repository
README context, independent AI budgets, bounded model input, implicit credential
isolation, crash recovery and preservation of failed AI status in later reports.
The reviewer found no remaining important code blocker in the bounded batch scope.

Runtime dependency audit: pip-audit 2.10.1 checked all **nine** pinned runtime
packages against PyPI's advisory service on 24 September 2026: **zero known
vulnerabilities, zero skipped packages**. This is not proof of absence of
vulnerabilities and does not cover Debian packages or native libraries in wheels.

The final image was separately scanned using verified Trivy 0.74.0 and its dated
public advisory database. Moving to Debian Trixie removed all five baseline
critical findings, and removing pip/ensurepip eliminated installer findings.
The final image has **zero critical and zero Python findings**, but retains
**44 high occurrences across eight unique OS CVEs**, with no Trixie fixes listed
at scan time. This is not a clean security approval: see
[deploy/SECURITY.md](deploy/SECURITY.md) for scope and open acceptance.

## Report and browser checks

The Word generator provides dated, scoped findings and distinguishes fresh
results, retained history, waiting candidates and collection issues. CSV labels
fresh/historical rows and escapes formula-like source text. JSON preserves the
full evidence and run history. The final live Word report was rendered with the
canonical DOCX renderer; all seven pages were visually inspected. A five-page
synthetic report also passed visual review of failed/pending AI and historical
findings. Historical AI disclosures stay with their scope; no clipping or table
layout defects remain in these samples. Reports and renders are retained locally.

Real Chrome interaction is currently blocked by `ERR_BLOCKED_BY_CLIENT` at the
local preview URL. HTTP and JavaScript tests passed, but they are not a substitute
for browser interaction/visual acceptance. The user has been asked to allow the
local preview. This limitation must remain in the handoff until browser testing
is completed.

## Remaining gates

1. Approved AI endpoint, model entitlement and data policy. The optional adapter
   is tested with controlled provider responses; no live model call was made.
2. Browser interaction check after the local Chrome block is resolved.
3. Stakeholder acceptance of evidence usefulness and false-positive/negative
   behavior on additional representative scopes.
4. Internal batch staging host, private report access, durable state, retention,
   source quotas, alerts, backup/restore and operational ownership before weekly
   deployment. The local UI is not the production service and remains loopback-only.
5. Security-owner review of the residual base-image advisories documented in
   [deploy/SECURITY.md](deploy/SECURITY.md). Scanning and reducing advisories does
   not constitute release approval or an exception.

PoC1 PR 1092 is unchanged. PoC2 is isolated on its own branch and CI workflow.
There was no external report publication, public catalog write, enabled crawler
schedule, production deployment or maintainer contact.

## Local evidence

Ignored validation evidence is under `.poc/production-review/`: final local and
native test logs, JUnit, input hashes, container build/default-command smoke,
actual cleanup checks, final HTTP results and live run output. Runtime advisory
results are under `.poc/validation/production-runtime-pip-audit.*`.
Final live reports are under `.poc/production-live/`; original repeat-memory
evidence remains under `.poc/repeat-check/` and `.poc/validation/`.
Generated findings and private local paths are not committed as report artifacts.
The PR's GitHub checks provide remote validation of the submitted commit.
