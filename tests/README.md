# Package Testing Infrastructure

Welcome to the Arm Ecosystem Dashboard package testing system. This directory contains the current documentation and starter template for the production testing pipeline used on `smoke_tests`.

## 📚 Documentation Guide

### **[COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md)** - Your Main Resource
Start here for the full current design:
- system overview and live architecture
- adding or moving package workflows
- output contract and result schema
- regression-validation policy
- troubleshooting and deployment guidance

### **[PIPELINE_REFERENCE.md](./PIPELINE_REFERENCE.md)** - Advanced Topics
Use this for deeper maintenance and pipeline work:
- batch/orchestrator flow
- collector and summary internals
- performance and timeout tuning
- debugging missing or misleading results
- advanced workflow patterns

---

## 🚀 Quick Start (15-20 Minutes)

### 1. **Understand the Current System**
- Package workflows run on native `ubuntu-24.04-arm` runners.
- Each package workflow is a reusable `workflow_call` job with a shared output contract.
- The repo is no longer a single "test-all-packages" workflow.
- Production execution is now:
  - package workflow
  - batch workflow
  - batch collector
  - global summary
  - published JSON in `data/test-results/` and `data/test-results-index.json`

### 2. **Copy the Template**

```bash
cp tests/template-package-test.yml .github/workflows/test-redis.yml
```

### 3. **Customize for Your Package**

Edit `test-redis.yml` and replace placeholders:
- `<PACKAGE>` → `Redis`
- `<package>` → `redis`

Then customize:
- installation logic
- version detection
- Tests 1-5 baseline smoke checks
- Test 6 regression validation policy
- the package page path, which is now typically `content/linux/opensource_packages/<package>.md`

### 4. **Add the Package to One Batch**

Add the new workflow to exactly one batch file such as:

```yaml
jobs:
  test-redis:
    uses: ./.github/workflows/test-redis.yml
```

Also add it to that batch file's `summary.needs` list.

You do **not** need to edit the orchestrator when adding a normal package. The orchestrator already triggers all batch workflows.

### 5. **Run and Verify**

Useful checks:

```bash
# Start the local dashboard
hugo server --bind 127.0.0.1 --port 1313

# Run one workflow manually from GitHub Actions
gh workflow run test-redis.yml --ref smoke_tests
```

After the batch and global summary complete, verify:
- `data/test-results/redis.json`
- `data/test-results-index.json`
- dashboard row and package page

### 6. **See the Dashboard Result**

Current frontend behavior:
- per-package row status is driven by `data/test-results-index.json`
- detailed package pages and drilldowns use `data/test-results/<slug>.json`
- regression tables come from the global summary workflow, not directly from package workflows

---

## 📊 System Overview

```text
test-<package>.yml
  └─ emits contract v2.0 outputs only

test-all-packages-batchN.yml
  ├─ runs many package workflows in parallel
  └─ uses .github/actions/collect-batch-results
       to build canonical per-package JSON artifacts for the batch

test-all-packages-orchestrator.yml
  ├─ triggers all 21 batches
  ├─ waits for them to finish
  └─ triggers test-all-packages-summary.yml

test-all-packages-summary.yml
  ├─ downloads batch artifacts
  ├─ assembles candidate + previous production results
  ├─ resolves exact job URLs
  ├─ normalizes result status from real test counts
  ├─ writes data/test-results/*.json
  └─ writes data/test-results-index.json

Hugo dashboard
  ├─ row templates read data/test-results-index.json
  └─ package details read data/test-results/*.json
```

---

## 🎯 Current Status

- Shared result contract: `2.0`
- Execution model: `21` batch workflows plus one orchestrator and one global summary
- Result publication model: centralized in the global summary workflow
- Regression policy model:
  - real Test 6 for non-package-manager lanes
  - explicit not-applicable for package-manager-installed lanes
  - explicit deferred/skipped decisions for honest non-failing cases
- Dashboard status source:
  - `data/test-results-index.json` for row lookups
  - `data/test-results/*.json` for canonical per-package payloads

---

## 🔧 Key Files

- [tests/template-package-test.yml](./template-package-test.yml)
  - starter reusable workflow template
- [tests/COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md)
  - current end-to-end guide
- [tests/PIPELINE_REFERENCE.md](./PIPELINE_REFERENCE.md)
  - technical deep dive
- `.github/workflows/test-all-packages-batch*.yml`
  - batch execution groups
- `.github/workflows/test-all-packages-orchestrator.yml`
  - batch dispatcher and waiter
- `.github/workflows/test-all-packages-summary.yml`
  - production data publisher and report generator
- `.github/actions/collect-batch-results/action.yml`
  - batch artifact collector and canonical JSON builder
- `data/test-results/*.json`
  - published per-package canonical results
- `data/test-results-index.json`
  - frontend lookup index for package rows
- `themes/arm-design-system-hugo-theme/layouts/partials/package-display/row-sub.html`
  - row-level frontend consumer of the index

---

## 📖 Learn More

- New maintainer: read [COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md)
- Collector / summary maintainer: read [PIPELINE_REFERENCE.md](./PIPELINE_REFERENCE.md)
- Adding a package: start from [template-package-test.yml](./template-package-test.yml)

---

## 🤝 Contributing

When adding a new package:
1. Copy `template-package-test.yml` to `.github/workflows/test-<package>.yml`.
2. Customize baseline install, version detection, and Tests 1-5.
3. Decide whether Test 6 is:
   - applicable
   - package-manager not applicable
   - honest deferred for no newer stable Arm64 candidate
4. Add the workflow to exactly one batch file and update that batch's `summary.needs`.
5. Validate syntax before pushing.
6. Let the orchestrator/global summary publish canonical JSON.

Do **not** hand-edit:
- `data/test-results/*.json`
- `data/test-results-index.json`

Those are generated by the Actions pipeline.

---

## 📝 Schema Reference (Quick)

Current published result schema is `2.0`, for example:

```json
{
  "schema_version": "2.0",
  "package": {
    "name": "ACL",
    "version": "3.6.5"
  },
  "run": {
    "status": "success",
    "url": "https://github.com/.../job/...",
    "runner": {
      "os": "ubuntu-24.04",
      "arch": "arm64"
    }
  },
  "tests": {
    "passed": 6,
    "failed": 0,
    "skipped": 0,
    "details": []
  },
  "metadata": {
    "contract_version": "2.0",
    "package_slug": "acl",
    "badge_status": "passing",
    "regression_applicability": "applicable",
    "regression_decision": "next_install_validated"
  }
}
```

For the full schema and field meanings, see [COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md#json-schema).

---

Questions or unclear behavior? Start with [COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md), then use [PIPELINE_REFERENCE.md](./PIPELINE_REFERENCE.md) for the exact execution and publishing flow.
