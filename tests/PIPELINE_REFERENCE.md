# Pipeline Reference - Technical Deep Dive

**Navigation:**
- [README](README.md) - quick start
- [Complete Guide](COMPLETE_GUIDE.md) - primary reference
- this document - internals, maintenance, and advanced patterns

---

## Table of Contents

- [Pipeline Flow](#pipeline-flow)
- [Advanced Customization](#advanced-customization)
- [Performance Optimization](#performance-optimization)
- [Debugging](#debugging)
- [Complex Scenarios](#complex-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting Guide](#troubleshooting-guide)
- [Reference](#reference)

---

## Pipeline Flow

### Detailed Execution Sequence

```text
1. Orchestrator trigger
   - scheduled
   - manual
   - push to main/smoke_tests for relevant files

2. Orchestrator dispatches batch1..batch19
   - each batch is a reusable workflow group
   - each batch runs many package workflows in parallel

3. Package workflow execution
   - checkout
   - metadata
   - install baseline
   - version detection
   - Tests 1-5 baseline smoke checks
   - Test 6 regression validation or applicability decision
   - summary outputs contract v2.0

4. Batch summary job
   - receives needs outputs for all package jobs
   - calls .github/actions/collect-batch-results
   - writes canonical per-package JSON files for that batch
   - uploads batch artifact

5. Orchestrator waits for all batches
   - tracks run ids
   - polls status until all complete

6. Global summary workflow
   - downloads batch artifacts
   - loads previous production results from data/test-results/
   - assembles candidate current-run results
   - synthesizes missing-package failures if a job never emitted results
   - resolves exact package job URLs when possible
   - normalizes published status from test counts
   - promotes candidate results into production
   - rewrites data/test-results/*.json
   - rewrites data/test-results-index.json
   - commits aggregated results with [skip ci]

7. Hugo frontend render
   - row templates read test-results-index.json
   - detailed package views use data/test-results/<slug>.json
```

### Timing Breakdown

There are now three time layers to think about:

**Package workflow**
- usually seconds to minutes
- heavy source builds can be much longer

**Batch workflow**
- bounded by the slowest package in the batch

**Global summary**
- usually fast
- dominated by artifact download, URL normalization, and file publication

Typical flow:

```text
Package job      -> 1m to 15m for normal packages
Heavy package    -> 20m to 45m+ for large source builds
Batch summary    -> < 1m after package jobs finish
Global summary   -> a few minutes after all batches finish
```

---

## Advanced Customization

### Custom Workflow Pattern

Use the template when possible, but for complex packages keep these rules:

- preserve the reusable workflow output contract
- keep Tests 1-5 as baseline smoke checks
- keep Test 6 semantics explicit
- do not publish production JSON inside the package workflow

Recommended structure:

```yaml
jobs:
  test-package:
    runs-on: ubuntu-24.04-arm
    outputs:
      contract_version: "2.0"
      package_slug: ...
      package_name: ...
      package_version: ...
      run_status: ...
      badge_status: ...
      core_failed: ...
      tests_passed: ...
      tests_failed: ...
      tests_skipped: ...
      duration_seconds: ...
      regression_status: ...
      regression_decision: ...
      regression_result: ...
      regression_comparison: ...
      regression_current_version: ...
      regression_latest_version: ...
      regression_next_installed_version: ...
      regression_policy: ...
```

### Multi-Version Testing

The current product model publishes one canonical row per package. If you temporarily test multiple versions:
- keep only one baseline row as the published truth
- ensure Test 6 still collapses to one regression decision
- avoid publishing multiple package variants into `data/test-results/`

### Conditional Testing

Common current patterns:

**Package-manager installed**
- emit `not_applicable_package_manager`
- do not fake Test 6

**No newer stable candidate**
- emit `no_newer_stable_available`

**Next candidate exists but lacks Arm64 assets**
- use honest deferred decisions such as:
  - `hold_current_arm_dependency_gap`
  - `manual_review_needed`

---

## Performance Optimization

### Caching Dependencies

Use caches for:
- heavy source builds
- repeated upstream archives
- package registries and toolchains

Examples:
- Bazel caches
- Maven/Gradle caches
- cargo/pip/npm caches
- extracted upstream archives where safe

### Parallel Test Execution

Parallelism now happens primarily at the batch level:
- many package workflows in the same batch
- 21 batches orchestrated across the whole repo
- package pages now primarily live under `content/linux/opensource_packages/`, with legacy compatibility for older `content/opensource_packages/` trees

When adding a new package:
- place it in one batch only
- keep heavy workflows distributed across batches

### Timeout Management

Current timeout-risk packages usually fall into:
- large archive download + extract
- slow source build
- multi-dependency service stack bring-up

If a package is consistently timing out:
1. reduce work
2. add cache
3. increase timeout only after measuring

---

## Debugging

### Enable Debug Logging

Inside a workflow step:

```bash
set -euxo pipefail
```

Use it selectively on the failing step, not every step.

### Capture Detailed Logs

Helpful command:

```bash
gh run view <run-id> --log
```

For package debugging, inspect:
1. package workflow log
2. batch summary job log
3. global summary log

### Interactive Debugging

Best local checks:

```bash
hugo server --bind 127.0.0.1 --port 1313
```

Then compare:
- package workflow logic
- `data/test-results/<slug>.json`
- `data/test-results-index.json`
- dashboard output

### Common Debug Patterns

**Actions green, dashboard red**
- stale production JSON still published
- latest failed job may not have replaced prior JSON

**Package row in wrong table**
- inspect normalized counts in the summary pipeline
- check whether `tests.passed`, `tests.failed`, and `core_failed` are correct

**Regression shown as failed when it should be deferred**
- check Test 6 `decision`
- check whether the workflow used `status=failed` instead of `status=skipped`

**Missing exact job URL**
- collector may have published with warning
- summary can fall back to the run URL when exact job URL resolution fails

---

## Complex Scenarios

### Database Testing

For databases and services:
- install baseline
- verify version
- start the service
- run one real command/query
- keep Test 5 small and deterministic

### Container Testing

For image-based packages:
- verify image availability on Arm64
- do not assume `amd64` tags are valid
- if only x86 assets exist for the next version, defer honestly

### Language-Specific Testing

Examples:

**Python**
- import check
- CLI check if applicable

**Java**
- prefer exact version extraction from package or service metadata
- watch for JDK mismatches between baseline and candidate

**Source build packages**
- minimize optional dependencies
- prefer system libraries when upstream supports them
- make the smoke test small after the build

---

## Best Practices

### Test Design

Recommended progression:

```text
Phase 1: binary or install existence
Phase 2: version/help verification
Phase 3: Arm64 architecture verification
Phase 4: one real functional smoke check
Phase 5: regression validation or honest applicability/deferred decision
```

### Error Handling

Use these rules:
- fail baseline steps honestly
- fail Test 6 only for real regression failures
- skip Test 6 for honest non-failing conditions
- do not let cleanup flip a green package red

### Maintenance

When a package changes:
- update the package workflow
- do not hand-edit production JSON
- verify the batch assignment still makes sense
- verify regression policy still matches the current package lane

---

## Troubleshooting Guide

### Issue: Tests Pass Locally But Fail in CI

Common causes:
- Ubuntu Arm64 package availability differs from your local machine
- runner network behavior differs
- source builds need more disk or time
- candidate artifact is x86-only

### Issue: Flaky Tests

Use:
- retries for artifact downloads
- explicit service readiness checks
- exact version parsing instead of full-string equality

### Issue: Version Detection Fails

Pattern:

```bash
tool --version 2>&1 | grep -oE '[0-9]+([.][0-9]+)+' | head -1 || echo "unknown"
```

Prefer exact semver extraction over comparing entire banner strings.

---

## Reference

### Exit Codes

- `0` → successful step
- nonzero → failing step
- skipped/deferred/not-applicable should normally remain non-failing at the step level

### Environment Variables

Common current workflow values:
- `github.run_id`
- `github.run_attempt`
- `github.job`
- `github.ref_name`
- package-specific version or install env vars

### Workflow Syntax

Current conventions:
- `workflow_call` outputs
- `if: always()` on summary steps
- Tests 1-5 may use step-level tolerance but must emit accurate outputs
- final summary/enforcement determines job success from normalized counts
