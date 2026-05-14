# Smoke-Test Architecture Diagrams

Current as of 2026-05-14.

This document is the high-level map for the Arm Ecosystem Dashboard smoke-test pipeline. It is intended for new team members who need to understand how package workflows, batch workflows, generated results, and the dashboard fit together.

## Operating Model

```text
main branch
  |
  | manual dispatch, workflow-path push, or weekly schedule
  v
.github/workflows/test-all-packages-orchestrator.yml
  |
  | starts all batch workflows
  v
.github/workflows/test-all-packages-batch1.yml
...
.github/workflows/test-all-packages-batch21.yml
  |
  | each batch runs package workflows through workflow_call
  v
.github/workflows/test-<package>.yml
  |
  | emits contract v2.0 outputs
  v
.github/actions/collect-batch-results
  |
  | creates batch result artifacts
  v
.github/workflows/test-all-packages-summary.yml
  |
  | merges batch artifacts, resolves job URLs, normalizes status
  v
data/test-results/<package>.json
data/test-results-index.json
  |
  | consumed by Hugo templates
  v
Linux dashboard package rows and test detail dropdowns
```

## Branch And Deployment Flow

```text
smoke-test development branch
  |
  | PR
  v
main
  |
  | full smoke-test orchestrator runs on main
  | results are reviewed on the staging/main dashboard
  v
production
  |
  | deploys the already validated site/results
  | does not rerun the full 21-batch smoke suite
  v
public production dashboard
```

Team decision: the full orchestrator should run weekly on `main`, then validated results should be promoted to `production`. Production results should point back to the main-run evidence.

## Schedule

The orchestrator has a weekly validation schedule:

```yaml
schedule:
  # Friday night in US Central time.
  # 03:00 UTC Saturday is 10 PM CDT / 9 PM CST Friday.
  - cron: '0 3 * * 6'
```

GitHub Actions schedules use UTC, so the local Central time changes with daylight saving time.

## Package Workflow Contract

Each active package workflow follows this shape:

```text
test-<package>.yml
  |
  | Test 1-5: baseline package proof on ubuntu-24.04-arm
  | Test 6: regression / next-version / not-applicable decision
  v
contract_version: 2.0
package_slug
package_name
package_version
run_status
badge_status
core_failed
tests_passed
tests_failed
tests_skipped
duration_seconds
regression_status
regression_decision
regression_result
regression_comparison
run_id / run_attempt / job_name
dashboard_link
timestamp
```

The package workflow does not directly publish production JSON. It emits standardized outputs. Batch collectors and the global summary publish canonical JSON.

## Dashboard Data Flow

```text
data/test-results-index.json
  |
  | fast lookup used by package rows
  v
row-sub.html
  |
  | displays badge summary and links to per-package detail
  v
expanded package row

data/test-results/<slug>.json
  |
  | canonical per-package detail payload
  v
test detail dropdown
```

Smoke-test badges are intentionally shown only for Open Source package pages. Commercial package rows do not display these Open Source smoke-test results.

## Current Result Inventory

The current local generated result set contains:

| Item | Count |
|---|---:|
| Active package workflows wired into batches | 960 |
| Batch package references | 960 |
| Published package result JSON files | 960 |
| Badge-passing packages | 960 |
| Packages showing `6/6` | 920 |
| Packages showing `5/5` | 40 |
| Orphan active workflows | 0 |
| Results without package pages | 0 |
| `works_on_arm: true` pages without results | 0 |

## What `6/6` And `5/5` Mean

`6/6` means Tests 1-5 passed and Test 6 also completed as a passing validation or an explicit passing policy result.

`5/5` means Tests 1-5 passed and Test 6 is intentionally not counted as a failed check. Typical reasons are:

- no newer stable Arm64 candidate exists
- the package-manager lane is not meaningful for next-version install validation
- a full runtime check requires special infrastructure outside the generic Arm runner

The key rule is that skipped/deferred Test 6 cases must be explicit and honest. They should not be represented as a failed package, and they should not claim full runtime validation if that runtime was not exercised.

## Disabled Workflow Archive

Unsupported packages can keep historical workflow source under:

```text
.github/workflows-disabled/
```

Files in that directory are not discovered by GitHub Actions. This is used only when the package page is marked `works_on_arm: false` and the workflow is removed from active batch orchestration.

Current examples include `curve`, `kettle`, and `mesos`.
