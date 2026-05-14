# Smoke-Test Branch Summary

Current as of 2026-05-14.

This file summarizes the current smoke-test implementation for reviewers and new maintainers. It replaces the older proof-of-concept summary that only described nginx and envoy.

## Current Branch Purpose

This branch is used to maintain and promote the production smoke-test system for the Linux Open Source package dashboard.

The system is no longer a two-package prototype. It now contains:

| Area | Current State |
|---|---|
| Active package workflows wired into batches | 960 |
| Batch workflows | 21 |
| Published result schema | 2.0 |
| Result publisher | `test-all-packages-summary.yml` |
| Row lookup file | `data/test-results-index.json` |
| Per-package detail files | `data/test-results/*.json` |
| Active orphan workflows | 0 |
| Result entries without package pages | 0 |

## High-Level File Map

| Path | Purpose |
|---|---|
| `.github/workflows/test-<package>.yml` | Individual reusable package workflow. |
| `.github/workflows/test-all-packages-batch*.yml` | Runs package workflows in groups. |
| `.github/workflows/test-all-packages-orchestrator.yml` | Starts all batches and the global summary. |
| `.github/workflows/test-all-packages-summary.yml` | Builds the canonical published JSON result set. |
| `.github/actions/collect-batch-results/action.yml` | Converts batch workflow outputs to result artifacts. |
| `.github/actions/apt-bootstrap/action.yml` | Shared apt retry/install helper for Arm runners. |
| `data/test-results/*.json` | Published per-package result payloads. |
| `data/test-results-index.json` | Fast dashboard row lookup index. |
| `content/linux/opensource_packages/*.md` | Open Source package pages that can display smoke-test badges. |
| `.github/workflows-disabled/` | Archive for unsupported/offboarded workflows that must not run. |

## Validation Model

Tests 1-5 are the baseline proof for each package. They should show the strongest honest Arm proof that package can provide on a generic Arm runner.

Examples:

- binary exists and reports version
- architecture is `aarch64` or `arm64`
- package imports successfully
- CLI help/version command runs
- service starts and responds locally
- tiny API, model, encode, build, or query workload completes
- Kubernetes or image manifests prove Arm-compatible published artifacts

Test 6 is the regression or policy lane. It should validate a newer version where meaningful, or explicitly record why the next-version path is skipped/deferred/not applicable.

## Dashboard Meaning

| Display | Meaning |
|---|---|
| `6/6 passing` | Six counted checks passed. |
| `5/5 passing` | Five counted checks passed; Test 6 is intentionally skipped/deferred/not applicable and is not counted as failure. |
| Red / failed | One or more counted checks failed. |

The dropdown remains the source of detailed truth. The top-level badge is a concise summary.

## Production Cadence

Agreed team cadence:

1. Run the full orchestrator weekly on `main`.
2. Review results on the main/staging dashboard.
3. Promote validated results to `production`.
4. Production deploys the site and uses the validated main result evidence.

The weekly schedule is Friday night Central:

```yaml
schedule:
  - cron: '0 3 * * 6'
```

That is 03:00 UTC Saturday, which maps to Friday evening in US Central time.

## Recent Cleanup Decisions

| Item | Decision | Reason |
|---|---|---|
| `curve` workflow | Moved to `.github/workflows-disabled/` | Curve is `works_on_arm: false` and is not part of active batch orchestration. |
| `garden-runc-release` workflow/result | Removed from active smoke-test set | No matching dashboard package page existed, and smoke-test work should not add new package metadata on its own. |
| Stale branch docs | Rewritten | Previous docs described the old nginx/envoy prototype and stale branch state. |

## Rules For Future Maintainers

- Do not leave active package workflows in `.github/workflows` unless exactly one batch references them.
- Do not leave generated result JSON without a matching Open Source package page.
- Do not show Open Source smoke-test badges on commercial package rows.
- Do not fake Test 6. If it cannot be meaningfully run, mark it explicitly as not applicable or deferred.
- Do not hand-edit generated JSON unless fixing an emergency publishing artifact with a follow-up workflow fix.
- Prefer fixing the workflow source so the next orchestrator run regenerates correct data.
