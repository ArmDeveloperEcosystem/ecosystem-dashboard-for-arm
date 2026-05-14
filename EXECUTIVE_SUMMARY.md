# Smoke-Test Executive Summary

Current as of 2026-05-14.

## Summary

The Arm Ecosystem Dashboard now has a production-ready smoke-test pipeline for Open Source Linux packages. The pipeline runs package-level checks on native Arm64 GitHub runners, publishes canonical JSON results, and displays concise status badges plus detailed test rows on the dashboard.

The current result set contains 960 active package smoke tests. All 960 are badge-passing in the local generated artifacts:

| Status | Count | Meaning |
|---|---:|---|
| `6/6` | 920 | Baseline checks and Test 6 completed as counted passing checks. |
| `5/5` | 40 | Baseline checks passed; Test 6 is explicitly skipped/deferred/not applicable and is not counted as failure. |
| Red / failing | 0 | No current package result is publishing as failed in the local artifact set. |

## What We Built

- Native Arm64 package validation using `ubuntu-24.04-arm` runners.
- Reusable package workflow contract version `2.0`.
- 21 batch workflows to keep the full test set manageable.
- A global summary workflow that publishes `data/test-results/*.json` and `data/test-results-index.json`.
- Dashboard support for top-level badge counts and expandable per-test details.
- A weekly orchestrator schedule on `main`.
- A production promotion model where production deploys validated main results rather than rerunning the full suite.

## Customer-Facing Interpretation

The dashboard is intentionally honest about validation depth.

For packages with full runtime smoke coverage, the result proves a representative Arm runtime path such as install, version, architecture check, service start, API request, CLI execution, or tiny workload.

For scoped Arm preflight packages, the result proves a real Arm-compatible surface but not necessarily the full production environment. Examples include GPU packages without live GPU execution, Kubernetes operators without a live cluster, GUI packages without a real desktop session, and cloud packages without authenticated cloud operations.

## Regression / Test 6 Policy

Test 6 is used to make the result future-facing when meaningful:

- next-version install or build validation
- next-release binary or bundle validation
- limited CPU-side validation for accelerator-heavy packages
- explicit no-newer-version or not-applicable decision when a real next-version check is not meaningful

Skipped or deferred Test 6 decisions are not treated as package failures if Tests 1-5 passed and the workflow explains the reason.

## Branch And Production Policy

Team-agreed operating model:

- Run the full smoke-test orchestrator weekly on `main`.
- Review the main/staging results.
- Merge the validated results to `production`.
- Production should deploy the site and point back to main-run evidence.
- Production should not rerun the full 21-batch smoke suite unless the team intentionally changes that policy.

## Current Cleanup State

Before production promotion, we checked for accidental dead files and mismatches:

- Active package workflows match batch references: 960 to 960.
- No active orphan package workflows remain.
- No generated result points to a missing Open Source package page.
- Unsupported/offboarded workflows are archived outside `.github/workflows`.
- Stale onboarding docs have been rewritten to match the current production design.

## Package Metadata Boundary

Smoke-test workflows should not create new dashboard package entries by themselves. If a generated result points to a package page that does not exist, either the owning content team should add the package metadata, or the workflow/result should be removed from the active smoke-test set before production.
