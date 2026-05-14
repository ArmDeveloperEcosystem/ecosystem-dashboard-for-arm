# Package Testing Framework - Complete Guide

**Quick Navigation:**
- [Overview](#overview)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Adding New Packages](#adding-new-packages)
- [JSON Schema](#json-schema)
- [Troubleshooting](#troubleshooting)
- [Deployment](#deployment)
- [Reference](#reference)

---

## Overview

### What This Is

This repository now uses a centralized package-testing architecture for the Arm Ecosystem Dashboard that:
- runs package tests on native Arm64 GitHub runners
- keeps package workflows reusable and contract-driven
- groups packages into `19` batch workflows
- centralizes JSON generation and publication
- renders dashboard package state from canonical JSON files

The current system is **not** the older model where each package workflow committed its own result JSON.

### Current Status

Current production design:
- package workflow contract version: `2.0`
- package workflows are reusable `workflow_call` jobs
- batch workflows run packages in parallel and collect canonical batch results
- orchestrator triggers all batches and then the global summary
- global summary publishes:
  - `data/test-results/<package>.json`
  - `data/test-results-index.json`

### How It Works

```text
1. A package workflow runs Tests 1-5 and optional Test 6
2. The workflow emits reusable outputs only
3. A batch workflow collects those outputs with collect-batch-results
4. Batch artifacts are uploaded
5. The orchestrator waits for all 21 batches
6. The global summary downloads all batch artifacts
7. It assembles candidate results and previous production results
8. It normalizes statuses and resolves exact job URLs
9. It writes canonical JSON to data/test-results/
10. It writes data/test-results-index.json
11. Hugo reads the index and per-package JSON at build time
```

---

## Quick Start

### Adding a New Package (15-20 minutes)

**Step 1:** Copy the template

```bash
cp tests/template-package-test.yml .github/workflows/test-redis.yml
```

**Step 2:** Replace placeholders

Update:
- `<PACKAGE>` → display name, for example `Redis`
- `<package>` → canonical slug, for example `redis`

The slug must match the package page basename in:
- `content/linux/opensource_packages/<package>.md`

**Step 3:** Implement baseline install and Tests 1-5

Tests 1-5 are the baseline smoke checks and decide:
- package `run_status`
- badge `badge_status`
- whether baseline passed

Typical baseline tasks:
- install package
- detect version
- binary or service existence
- version/help command
- Arm64 verification
- one real functional smoke check

**Step 4:** Choose the correct Test 6 policy

There are two normal paths:

1. **Applicable regression validation**
- use this when the tested artifact comes from:
  - source build
  - direct tarball
  - direct binary
  - custom image
  - manual upstream artifact

2. **Package-manager installed, not applicable**
- use this when Tests 1-5 install via:
  - `apt`
  - `dnf`
  - `yum`
  - `zypper`
  - `apk`
  - `snap`
  - `pip`
  - `npm`
  - `cargo`
  - or another package ecosystem

In the not-applicable case, do **not** fake a next-version install. Emit a clear `not_applicable_package_manager` result instead.

**Step 5:** Add the workflow to one batch

Pick exactly one batch file:
- `.github/workflows/test-all-packages-batchN.yml`

Add:

```yaml
jobs:
  test-redis:
    uses: ./.github/workflows/test-redis.yml
```

Then add `test-redis` to that batch file's `summary.needs` list.

Do **not** edit the orchestrator for ordinary package additions. It already dispatches every batch file.

**Step 6:** Validate locally

Useful checks:

```bash
# Run the Hugo dashboard locally
hugo server --bind 127.0.0.1 --port 1313

# Inspect workflow syntax
python3 - <<'PY'
import yaml, pathlib
path = pathlib.Path('.github/workflows/test-redis.yml')
yaml.safe_load(path.read_text())
print('yaml ok')
PY
```

**Step 7:** Push and verify

After pushing to `smoke_tests`:
- package workflow runs inside a batch
- batch uploads artifacts
- orchestrator triggers global summary
- global summary republishes canonical JSON

Verify:
- `data/test-results/redis.json`
- `data/test-results-index.json`
- dashboard row and package page

**Pro tips**
- Copy the most similar existing workflow, not just the generic template.
- Keep Tests 1-5 baseline-focused.
- Be explicit in Test 6 output fields.
- Prefer honest `skipped`/deferred outcomes over fake greens or fake reds.

---

## Architecture

### System Components

**Package workflows**
- located in `.github/workflows/test-<package>.yml`
- reusable via `workflow_call`
- emit contract `2.0` outputs
- do not publish production JSON directly

**Batch workflows**
- files: `.github/workflows/test-all-packages-batch1.yml` through `batch19.yml`
- run many package workflows in parallel
- each batch has a `summary` job
- `summary` calls `.github/actions/collect-batch-results`

**Collector action**
- file: `.github/actions/collect-batch-results/action.yml`
- builds canonical per-package JSON from `needs` outputs
- normalizes success/failure from actual test counts
- resolves exact package job URLs when possible

**Orchestrator**
- file: `.github/workflows/test-all-packages-orchestrator.yml`
- scheduled daily at `2 AM UTC`
- also runs on relevant pushes to `main` and `smoke_tests`
- dispatches all `19` batches
- waits for them to complete
- triggers the global summary

**Global summary**
- file: `.github/workflows/test-all-packages-summary.yml`
- downloads batch artifacts
- assembles candidate and previous-production staging sets
- synthesizes missing results when a package failed before publishing outputs
- promotes validated candidate results to production data
- rewrites:
  - `data/test-results/*.json`
  - `data/test-results-index.json`

**Frontend**
- package rows read `data/test-results-index.json`
- package detail pages use canonical JSON in `data/test-results/*.json`

### End-to-End Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                 GitHub Actions on ubuntu-24.04-arm                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────────┐                                           │
│  │ test-<package>.yml           │                                           │
│  │ - install baseline           │                                           │
│  │ - Tests 1-5                  │                                           │
│  │ - Test 6 or applicability    │                                           │
│  │ - emit contract v2.0 outputs │                                           │
│  └──────────────┬───────────────┘                                           │
│                 │                                                           │
│                 ├────────────────────────────────────────────────────┐      │
│                 │                                                    │      │
│  ┌──────────────▼───────────────┐   ┌──────────────▼───────────────┐ │      │
│  │ test-all-packages-batch1.yml │   │ test-all-packages-batch19.yml│ │ ...  │
│  │ - many package jobs          │   │ - many package jobs          │ │      │
│  │ - summary job                │   │ - summary job                │ │      │
│  │ - collect-batch-results      │   │ - collect-batch-results      │ │      │
│  └──────────────┬───────────────┘   └──────────────┬───────────────┘ │      │
│                 │                                  │                 │      │
│                 └───────────────┬──────────────────┴─────────────────┘      │
│                                 │                                            │
│                  batchN-test-results artifacts                               │
│                                 │                                            │
│  ┌──────────────────────────────▼───────────────────────────────┐            │
│  │ test-all-packages-orchestrator.yml                           │            │
│  │ - triggers all 21 batches                                   │            │
│  │ - waits for completion                                      │            │
│  │ - triggers global summary                                   │            │
│  └──────────────────────────────┬───────────────────────────────┘            │
│                                 │                                            │
│  ┌──────────────────────────────▼───────────────────────────────┐            │
│  │ test-all-packages-summary.yml                                │            │
│  │ - downloads batch artifacts                                  │            │
│  │ - assembles candidate + previous production results          │            │
│  │ - synthesizes missing-package failures when needed           │            │
│  │ - resolves exact job URLs                                    │            │
│  │ - normalizes status from actual test counts                  │            │
│  │ - publishes canonical production JSON                        │            │
│  └──────────────────────────────┬───────────────────────────────┘            │
│                                 │                                            │
└─────────────────────────────────┼────────────────────────────────────────────┘
                                  │
                                  ▼
         ┌───────────────────────────────────────────────────────────┐
         │ data/test-results/<package>.json                         │
         │ data/test-results-index.json                             │
         └──────────────────────────────┬────────────────────────────┘
                                        │
                                        ▼
         ┌───────────────────────────────────────────────────────────┐
         │ Hugo dashboard                                            │
         │ - row templates use test-results-index.json               │
         │ - package detail views use data/test-results/*.json       │
         └───────────────────────────────────────────────────────────┘
```

### Installation Command Examples

**APT package**
```yaml
- name: Install Redis
  id: install
  run: |
    set -euo pipefail
    sudo apt-get update
    sudo apt-get install -y redis-server
```

**Binary download**
```yaml
- name: Install tool
  id: install
  run: |
    set -euo pipefail
    curl -L -o tool.tar.gz "https://example.com/tool-1.2.3-linux-arm64.tar.gz"
    tar -xzf tool.tar.gz
    sudo install -m 0755 tool /usr/local/bin/tool
```

**Source build**
```yaml
- name: Install package from source
  id: install
  run: |
    set -euo pipefail
    git clone --depth 1 --branch v1.2.3 https://github.com/example/project.git
    cd project
    ./configure
    make -j"$(nproc)"
    sudo make install
```

### Version Command Examples

**Simple binary**
```bash
tool --version 2>&1 | grep -oE '[0-9]+([.][0-9]+)+' | head -1
```

**Fallback parsing**
```bash
tool version 2>&1 | grep -oE '[0-9]+([.][0-9]+)+' | head -1 || echo "unknown"
```

**Library / package-config**
```bash
pkg-config --modversion libhelium || echo "unknown"
```

### Workflow Pattern

Current package workflow pattern:

1. metadata step
2. install step
3. version step
4. Tests 1-5 baseline smoke checks
5. optional Test 6 regression validation or applicability step
6. summary step
7. human-readable `GITHUB_STEP_SUMMARY`
8. final failure enforcement

Baseline Tests 1-5 decide:
- `core_failed`
- `badge_status`
- overall baseline health

Test 6 decides:
- regression pass
- regression fail
- regression skip/deferred/not-applicable

### Data Flow

```text
test-<package>.yml
  -> workflow_call outputs
  -> batch summary job
  -> collect-batch-results action
  -> batch artifact
  -> global summary
  -> data/test-results/<slug>.json
  -> data/test-results-index.json
  -> Hugo frontend
```

### Conflict Resolution

The old per-package "commit your own JSON" design is gone.

Current publish model:
- only the global summary writes production test JSON
- that means fewer cross-workflow git conflicts
- package workflows only emit outputs/artifacts

### Badge Generation and Display

Badge/state semantics today:
- `badge_status` is driven by baseline Tests 1-5
- row placement in Failed/Passing tables is normalized from **real counts**
- regression tables are separate from overall package tables

The current global summary renders separate sections for:
- summary statistics
- regression validation passed
- regression validation failed
- regression validation deferred / not applicable
- regression not configured / not emitted
- failed packages
- passing packages

---

## Adding New Packages

### The Template Approach

Use `tests/template-package-test.yml` as the starting point, but prefer copying a nearby working workflow when possible:

- package-manager workflow → copy another package-manager example
- source-build workflow → copy a source-build example
- tarball or binary workflow → copy a direct-download example
- container/image workflow → copy an image-based example

Keep the current output contract and summary structure intact.

### Examples to Learn From

Good current references:
- package manager / applicability:
  - `.github/workflows/test-timescaledb.yml`
- source build + real regression:
  - `.github/workflows/test-acl.yml`
- honest deferred next-version:
  - `.github/workflows/test-curve.yml`
- direct download / artifact validation:
  - `.github/workflows/test-new-relic.yml`

### Common Customizations

Common package-specific changes:
- swap `apt` for tarball download
- replace binary checks with service or HTTP checks
- patch source for current toolchain compatibility
- use staged install prefixes for regression candidate validation
- detect x86-only or missing Arm64 assets and defer honestly

### Test Command Best Practices

- keep Tests 1-5 small and deterministic
- use real functional checks, not only `--version`
- verify Arm64 architecture when installing binaries or libraries
- emit explicit Test 6 fields:
  - `current_version`
  - `latest_version`
  - `next_installed_version`
  - `decision`
  - `regression_result`
  - `comparison`
  - `status`
- use honest deferred reasons when appropriate:
  - `no_newer_stable_available`
  - `hold_current_arm_dependency_gap`
  - `not_applicable_package_manager`
  - `manual_review_needed`

---

## JSON Schema

### Schema Version 2.0

Current canonical result shape:

```json
{
  "schema_version": "2.0",
  "package": {
    "name": "ACL",
    "version": "3.6.5"
  },
  "run": {
    "id": "23875415786",
    "attempt": "1",
    "url": "https://github.com/.../job/69617150032",
    "timestamp": "2026-04-01T23:13:50Z",
    "status": "success",
    "runner": {
      "os": "ubuntu-24.04",
      "arch": "arm64"
    },
    "job_name": "test-acl / test-acl"
  },
  "tests": {
    "passed": 6,
    "failed": 0,
    "skipped": 0,
    "duration_seconds": 56,
    "details": []
  },
  "metadata": {
    "contract_version": "2.0",
    "package_slug": "acl",
    "dashboard_link": "/linux/opensource_packages/acl",
    "badge_status": "passing",
    "core_failed": 0,
    "batch_title": "Batch 1",
    "job_url_resolution_status": "central_exact",
    "regression_applicability": "applicable",
    "regression_status": "passed",
    "regression_decision": "next_install_validated",
    "production_refreshed_at": "2026-04-01T23:53:13.065354+00:00",
    "publish_state": "published"
  }
}
```

### Field Descriptions

**`package`**
- user-facing package identity

**`run`**
- the concrete job/run that produced the current published result

**`tests`**
- normalized total counts and per-step detail

**`metadata.contract_version`**
- reusable workflow contract version

**`metadata.badge_status`**
- frontend badge state derived from baseline smoke checks

**`metadata.core_failed`**
- number of failed baseline Tests 1-5

**`metadata.regression_*`**
- regression classification and explanation used by global summary tables

**`metadata.publish_state`**
- whether the row was published normally or with warnings

**`data/test-results-index.json`**
- aggregated map of the same package payloads used for fast frontend lookup

---

## Troubleshooting

### Badge Not Displaying

Check:
1. package slug matches `content/linux/opensource_packages/<slug>.md` (or the legacy root content path in older trees)
2. the workflow emits `package_slug` correctly
3. the package is present in `data/test-results-index.json`
4. the dashboard row template can find the canonical slug

### Workflow Failing to Publish Correct Results

Remember:
- package workflows do not publish production JSON directly
- inspect:
  - package workflow
  - batch summary job
  - collector output
  - global summary

If a package run is red in Actions but not on the dashboard, the old production JSON may still be in place because the latest failing package run did not publish a new canonical result.

### Version Detection Failing

Run the version command locally first:

```bash
tool --version 2>&1
```

Then choose the simplest stable extraction rule that works on Arm64.

### Tests Passing Locally But Failing in CI

Common causes:
- missing packages on `ubuntu-24.04-arm`
- network/download variability
- exact job timeout caps
- x86-only release assets
- unguarded `set -u` / `pipefail` behavior

### JSON Parsing Errors

Do not hand-edit:
- `data/test-results/*.json`
- `data/test-results-index.json`

Those are generated by the summary pipeline.

If a package row is missing, inspect:
- batch artifact JSON
- collector action
- global summary staging/publish steps

### Hugo Build Errors

Run locally:

```bash
hugo server --bind 127.0.0.1 --port 1313
```

If rows look stale:
- confirm `data/test-results-index.json` updated
- confirm the package slug matches the page filename

---

## Deployment

### Pre-Deployment Checklist

- workflow YAML parses cleanly
- shell blocks are syntax-valid
- package is assigned to exactly one batch
- batch `summary.needs` list includes the package
- Test 6 policy is honest
- no hand edits to published JSON
- dashboard renders locally with Hugo

### Deployment Steps

1. commit workflow/doc changes
2. push to `smoke_tests`
3. orchestrator dispatches batches
4. batches upload artifacts
5. global summary downloads artifacts and republishes canonical JSON
6. verify:
   - `data/test-results/*.json`
   - `data/test-results-index.json`
   - dashboard rows and package page

### Post-Deployment

Review:
- failed packages table
- regression failed table
- deferred/not applicable table
- any `published_with_warning` package rows

### Rollback Plan

If a workflow change is bad:

```bash
git revert <commit>
git push origin smoke_tests
```

If only a package workflow is bad, revert that workflow change rather than editing generated JSON directly.

---

## Advanced Topics

### Customizing the Template

The template is intentionally generic. For real packages you will usually customize:
- install lane
- version detection
- functional smoke check
- regression applicability
- summary wording

### Matrix Testing (Future)

Matrix testing is possible, but the current production system is optimized for:
- one published baseline per package
- one optional next-version regression decision per package

If matrix testing is introduced later, it should still collapse to one canonical published package row.

---

## Reference

### File Locations

- `tests/template-package-test.yml`
- `.github/workflows/test-<package>.yml`
- `.github/workflows/test-all-packages-batch*.yml`
- `.github/workflows/test-all-packages-orchestrator.yml`
- `.github/workflows/test-all-packages-summary.yml`
- `.github/actions/collect-batch-results/action.yml`
- `data/test-results/*.json`
- `data/test-results-index.json`
- `themes/arm-design-system-hugo-theme/layouts/partials/package-display/row-sub.html`

### Workflow Triggers

**Package workflows**
- `workflow_dispatch`
- `workflow_call`

**Orchestrator**
- daily schedule at `0 2 * * *`
- manual dispatch
- push to `main` or `smoke_tests` when relevant markdown/workflow files change

### Key Metrics

Current summary tracks:
- total packages
- passed / failed / malformed
- regression passed / failed / deferred / not applicable / not configured
- candidate rows promoted and published with warnings
- exact vs weak job URL resolution

---

## Getting Help

If you are adding or debugging a package:

1. start with `tests/template-package-test.yml`
2. compare with a similar live workflow
3. run Hugo locally
4. inspect the package workflow log
5. inspect the batch summary artifact
6. inspect the global summary output and published JSON

Useful commands:

```bash
# Start the dashboard
hugo server --bind 127.0.0.1 --port 1313

# View an Actions run log
gh run view <run-id> --log

# Validate one workflow YAML file
python3 - <<'PY'
import yaml, pathlib
print(yaml.safe_load(pathlib.Path('.github/workflows/test-example.yml').read_text()) is not None)
PY
```
