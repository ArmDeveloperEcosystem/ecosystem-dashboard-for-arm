# Strict package observation contract

This contract is the producer boundary for package smoke workflows. It is
deliberately dormant until every package workflow and every batch wrapper can
be migrated atomically.

## Trust boundary

A package job may report only facts it directly observed:

- canonical package identity and the exact baseline version;
- the status, name, and duration of Tests 1-6;
- counters and overall outcome derived from those six records;
- the approved Test 6 decision and meaningful comparison evidence.

It may not assert a trusted run ID, job ID, job URL, artifact ID, or batch
identity. The exact-run parent obtains those values from the GitHub API and
passes the untouched canonical output string to `bind_trusted_job()` to add
them. Parsed or normalized producer JSON is never accepted at that boundary.

## Fail-closed rules

- Tests 1-5 must each be `passed` or `failed`; a skipped baseline test is a
  baseline failure that must be represented honestly, not hidden as a skip.
- Test 6 may be raw `passed`, `failed`, or `skipped`, but its approved decision
  determines the semantic result: passed, failed, deferred, not applicable, or
  skipped because the baseline failed.
- Counts, duration, core failures, badge status, and run status must exactly
  match the six detail records. The contract never repairs or guesses them.
- Unknown decisions, placeholder versions, placeholder narratives, extra
  fields, and contradictory outcome claims are rejected.
- Canonical JSON is deterministic and contains no producer-supplied GitHub
  identity or credential-bearing value.
- Strings must use NFC normalization, and the canonical observation is capped
  at 16,384 ASCII bytes so an output cannot grow without bound.

## Components

- `package_result_policy.py` owns the reviewed Test 6 decision groups used by
  both the observation contract and the exact-run artifact validator.
- `package_observation.py` validates producer facts, emits canonical JSON, and
  binds a valid observation to trusted parent-supplied job identity.
- `../actions/emit-package-observation/action.yml` is the dormant composite
  action package workflows will call during the atomic migration.
- `../actions/collect-batch-results/action.yml` is the active legacy bridge.
  GitHub's Jobs API is the only source for each test detail's name, conclusion,
  duration, and exact step URL. Structured workflow outputs may add Test 6
  semantic fields, but their counters and decisions must agree with those API
  step records under the strict promoter. Job logs are never parsed as
  evidence, and the collector does not repair counters or step statuses.
- `../actions/collect-batch-results-v2/action.yml` is a dormant compatibility
  bridge that rejects malformed legacy outputs and log-derived status repairs.
  No batch wrapper references it.
- `promote_package_results.py` is the active fail-closed publication boundary.
  The summary workflow invokes its `compatibility` policy while producer
  migration is incomplete, but that exception applies only to previously
  published rows. Every new candidate always passes the strict six-test
  semantic policy. The summary builds `trusted-registrations.json` from the
  checked-in batch topology, the exact orchestration manifest, and GitHub's job
  API. Candidate batch, run, attempt, job name, and exact job URL must match
  that manifest. Carried previous rows use a separate historical registration
  set. Each historical run is resolved through GitHub's API and must originate
  from the protected `main` branch at a commit in the trusted `main` ancestry.
  The exact package job must carry `ubuntu-24.04-arm` without `self-hosted`
  and belong to GitHub's hosted runner group (ID 0, `GitHub Actions`). Its
  expected batch workflow, repository, attempt, package job URL, job name,
  conclusion, and execution window are bound before the old row may be
  retained. Historical identity is never accepted solely because the
  previous JSON is internally self-consistent.
  Candidate files cannot supply publisher-owned state, while
  retained previous rows must contain a valid publication timestamp and
  `publish_state: published`. The promoter also validates full row structure,
  filename identity, native Arm64 runner identity, counters, and status
  coherence without repairing evidence. An invalid candidate retains only a
  validated prior row; a missing or invalid prior row blocks the complete
  publication transaction.
- `tests/test_promote_package_results.py` executes the publish, retain, and
  blocked branches against real staging directories.
- `tests/test_package_observation.py` covers valid lanes and adversarial
  contradictions, including compatibility with `validate_package_result()`.
- `package_observation_migration_audit.py` inventories all registered workflows
  without editing them and emits a canonical remediation report. It follows
  local composite-action output bindings and counts only shell writes directed
  to `$GITHUB_OUTPUT`; comments, stdout-only text, and declarations without a
  producing step do not satisfy the audit. Output-writing shell functions count
  only when reachable from a call, and literal Test 6 decisions are paired with
  the status written by the same output transaction. Shared-smoke variable
  decisions are paired with their Test 6 status updates, and critical action and
  policy source digests are part of the reviewed report. The report also inventories
  baseline skip hazards, missing Test 6 baseline guards, missing strict
  observation steps, semantic input bindings, job and reusable-workflow output
  bindings, unsafe placeholder fallbacks, legacy batch collectors, the absent
  strict batch collector, and four disjoint producer-wiring cohorts whose union
  must remain the complete registered package set.

## Activation sequence

1. Add the observation output to all package reusable workflows.
2. Correct every counter and decision contradiction until all workflows emit a
   valid observation on native Arm64.
3. Add exact orchestration identity to all batch wrappers and collect only
   complete canonical observations.
4. Bind observations to exact GitHub API jobs, upload complete batch artifacts,
   and validate the aggregate attestation.
5. Enable draft-PR publication only after the complete shadow path is green.

The active promoter hardens publication behavior without changing any trigger,
batch assignment, package test, credential, or deployment. Its compatibility
setting permits only the explicitly audited legacy shapes of retained
production rows; it never weakens validation for a newly produced candidate.
The stricter producer observation policy remains dormant until migration is
complete.
The 22 production batch wrappers continue to reference
`collect-batch-results`; they must not be rewired to the v2 or strict
observation collector until the canonical audit is clean and the native Arm64
shadow run has passed. At strict cutover the same promoter switches from
`compatibility` to `strict`; source code cannot authorize that change.

Run the source audit locally with:

```bash
python3 .github/scripts/package_observation_migration_audit.py \
  --repository-root . \
  --output /tmp/package-observation-migration-audit.json
```

Add `--require-clean` after migration to return a nonzero status while any
remediation bucket remains. During the staged migration, the test suite pins a
reviewed digest of the complete report so one repaired workflow cannot be
silently replaced by a newly broken workflow.

`--require-activation-ready` is a separate fail-closed gate. It returns exit 3
unless every static remediation bucket is empty and the report explicitly
contains independently established cutover authorization. This source-only
auditor always emits `cutover_authorized: false`; it cannot authorize itself.
The strict observation runtime and native Arm64 shadow run remain the authority
for control-flow and execution evidence. The final workflow bytes must also
reseal the reviewed supply-chain lock before cutover. Both external gates are
recorded alongside the all-workflow observation migration and strict-collector
shadow-validation gates in every canonical audit report. The activation
orchestrator must verify all four gates; source code cannot approve its own
cutover.
