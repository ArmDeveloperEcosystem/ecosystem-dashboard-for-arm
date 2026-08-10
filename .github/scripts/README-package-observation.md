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
- `tests/test_package_observation.py` covers valid lanes and adversarial
  contradictions, including compatibility with `validate_package_result()`.

## Activation sequence

1. Add the observation output to all package reusable workflows.
2. Correct every counter and decision contradiction until all workflows emit a
   valid observation on native Arm64.
3. Add exact orchestration identity to all batch wrappers and collect only
   complete canonical observations.
4. Bind observations to exact GitHub API jobs, upload complete batch artifacts,
   and validate the aggregate attestation.
5. Enable draft-PR publication only after the complete shadow path is green.

Adding these files alone does not change any trigger, batch, package test,
credential, deployment, or publication behavior.
