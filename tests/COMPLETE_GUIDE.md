# Package Testing Framework - Complete Guide

**Quick Navigation:**
- [Overview](#overview)
- [Quick Start (5 min)](#quick-start)
- [Architecture](#architecture)
- [Adding Packages](#adding-packages)
- [JSON Schema](#json-schema)
- [Troubleshooting](#troubleshooting)
- [Deployment](#deployment)

---

## Overview

### What This Is

An automated functional testing system for packages in the Arm Ecosystem Dashboard that:
- ✅ Runs tests on native Arm64 GitHub runners
- ✅ Validates package installation and functionality
- ✅ Displays test results as badges on the dashboard
- ✅ Runs automatically daily at 2 AM UTC
- ✅ Scales easily from 2 to 20+ packages

### Current Status

**Packages Tested:**
- nginx (5 tests) ✅
- Envoy (4 tests) ✅

**Infrastructure:**
- 4 GitHub Actions workflows
- Reusable workflow template for rapid scaling
- Auto-conflict resolution with retry logic
- Badge integration in dashboard UI

### How It Works

```
1. GitHub Actions (Arm64 runner) → Scheduled daily or manual trigger
2. Install package → Run tests → Generate JSON results
3. Auto-commit to data/test-results/<package>.json
4. Hugo reads JSON at build time
5. Badge displays on dashboard: "Arm64 Tests: X passing"
```

---

## Quick Start

### Adding a New Package (10 minutes)

**Step 1:** Create workflow file `.github/workflows/test-<package>.yml`

```yaml
name: Test <Package> on Arm64

on:
  workflow_dispatch:
  push:
    branches: [main, smoke_tests]
    paths:
      - 'content/opensource_packages/<package>.md'
      - '.github/workflows/test-<package>.yml'
  workflow_call:

jobs:
  test-package:
    uses: ./.github/workflows/reusable-package-test.yml
    with:
      package_name: "<Package Display Name>"
      package_slug: "<package>"
      package_category: "<Category>"
      package_language: "<language>"
      install_commands: |
        [
          "sudo apt-get update",
          "sudo apt-get install -y <package>"
        ]
      version_command: "<package> --version | grep -oP '[0-9.]+'"
      test_commands: |
        [
          {"name": "Check binary exists", "command": "command -v <package>"},
          {"name": "Get version", "command": "<package> --version"},
          {"name": "Run help", "command": "<package> --help"}
        ]
```

**Step 2:** Add to orchestrator `.github/workflows/test-all-packages.yml`

```yaml
jobs:
  # ... existing jobs ...
  
  test-<package>:
    uses: ./.github/workflows/test-<package>.yml
  
  summary:
    needs: [test-nginx, test-envoy, test-<package>]  # Add to list
```

**Step 3:** Commit and run

```bash
git add .github/workflows/test-<package>.yml .github/workflows/test-all-packages.yml
git commit -m "Add <package> functional tests"
git push
```

**Step 4:** Trigger test in GitHub Actions

- Go to Actions → "Test <Package> on Arm64" → Run workflow
- Or wait for scheduled run (daily 2 AM UTC)

**Step 5:** Verify

- Check workflow completes successfully
- Verify `data/test-results/<package>.json` is created
- View badge on dashboard (package expanded view)

### Installation Command Examples

**APT package:**
```yaml
install_commands: |
  [
    "sudo apt-get update",
    "sudo apt-get install -y redis-server"
  ]
```

**Binary download:**
```yaml
install_commands: |
  [
    "sudo curl -L -o /usr/local/bin/binary https://releases.example.com/binary-arm64",
    "sudo chmod +x /usr/local/bin/binary"
  ]
```

**Python package:**
```yaml
install_commands: |
  [
    "pip install <package>"
  ]
```

**Docker image:**
```yaml
install_commands: |
  [
    "docker pull <image>:latest-arm64"
  ]
```

### Version Command Examples

**Simple:**
```bash
nginx -v 2>&1 | grep -oP 'nginx/\K[0-9.]+'
```

**With fallback:**
```bash
envoy --version 2>&1 | grep -oP 'version: [^/]+/\K[^/]+' || echo 'unknown'
```

**Python/Node:**
```bash
python -c "import <package>; print(<package>.__version__)"
node -p "require('./package.json').version"
```

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                  GitHub Actions (Arm64)                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐           │
│  │ test-nginx │  │ test-envoy │  │ test-pkg   │           │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘           │
│        └────────────────┴───────────────┘                   │
│                        │                                    │
│              ┌─────────▼─────────┐                          │
│              │ test-all-packages │ ◄── Daily 2 AM UTC      │
│              └─────────┬─────────┘                          │
└────────────────────────┼─────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────┐
         │ data/test-results/*.json  │
         └───────────┬───────────────┘
                     │
                     ▼
         ┌───────────────────────────┐
         │   Hugo Dashboard          │
         │   (Badge Display)         │
         └───────────────────────────┘
```

### Workflow Patterns

**Pattern 1: Reusable Workflow** (Recommended - 10 min to add)
```
test-<package>.yml (config) → reusable-package-test.yml (template) → Results
```
- Minimal configuration
- JSON-based setup
- Fast to add new packages
- Example: Envoy

**Pattern 2: Custom Workflow** (Advanced - 2 hours to create)
```
test-<package>.yml (full implementation) → Results
```
- Full control over test logic
- Complex scenarios (service management, HTTP testing)
- Example: nginx

### Data Flow

1. **Trigger** → Workflow starts (scheduled, manual, or on push)
2. **Install** → Package installed on Arm64 runner
3. **Test** → Execute test commands with timing
4. **Generate** → Create JSON results (schema v1.0)
5. **Commit** → Auto-commit to `data/test-results/`
6. **Resolve** → Auto-resolve git conflicts (if concurrent runs)
7. **Display** → Hugo reads JSON and shows badge

### Conflict Resolution

When multiple workflows run concurrently:
```
1. Each workflow commits its own JSON file
2. Git pull --rebase before push
3. If conflict: git checkout --ours (take our version)
4. Retry up to 5 times with exponential backoff (2s, 4s, 6s, 8s, 10s)
5. Successfully push results
```

### Badge Generation and Display

**How Badges Appear on the Dashboard:**

The badge system uses **direct template integration** rather than Hugo shortcodes:

1. **Data Source:**
   - Workflows generate JSON files in `data/test-results/<package>.json`
   - JSON follows schema v1.0 (see Test Results JSON Schema section)

2. **Template Integration:**
   - File: `themes/arm-design-system-hugo-theme/layouts/partials/package-display/row-sub.html`
   - This template renders the expanded package details when users click a package card
   - It automatically reads test data from the JSON files

3. **Badge Rendering Logic:**
   ```go-html-template
   {{- $packageSlug := .metadata.File.ContentBaseName -}}
   {{- $testData := index $.metadata.Site.Data "test-results" $packageSlug -}}
   {{- if $testData -}}
     <!-- Badge HTML rendered here -->
   {{- end -}}
   ```

4. **Badge Features:**
   - **Color-coded status**: Green (#28a745) for passing, Red (#dc3545) for failing
   - **Test summary**: "🔧 Arm64 Tests: X passing/failing"
   - **Clickable link**: Links to GitHub Actions run URL
   - **Metadata display**: Shows last tested timestamp and version
   - **Expandable details**: 
     - Individual test results with ✅/❌ indicators
     - Test duration for each test
     - Total duration and runner information

5. **Automatic Display:**
   - No manual configuration needed
   - Badge appears automatically when:
     - JSON file exists in `data/test-results/`
     - Package slug matches (e.g., `nginx.md` → `nginx.json`)
     - Hugo build succeeds
   - Badge only visible in **expanded package view** (click package to expand)

**Important Notes:**

- **Shortcode not used**: A `test-badge.html` shortcode exists but is NOT used because the dashboard doesn't render individual package pages
- **No manual setup**: Don't add `{{< test-badge >}}` to package markdown files - it won't work
- **Template-based**: Badge integration is handled entirely in the `row-sub.html` template

**Viewing Badges:**

1. Start Hugo: `hugo server -D`
2. Open: http://localhost:1313/
3. Search for or scroll to the package (e.g., "nginx")
4. Click the package card to expand it
5. Badge appears in the expanded section with test details

**Direct Link Pattern:**
- http://localhost:1313/?package=nginx (auto-expands nginx)

---

## Adding Packages

### Method 1: Simple Packages (Recommended)

Use the reusable workflow template for packages with straightforward tests.

**Example: Adding Redis**

1. Create `.github/workflows/test-redis.yml`:

```yaml
name: Test Redis on Arm64

on:
  workflow_dispatch:
  push:
    branches: [main, smoke_tests]
    paths:
      - 'content/opensource_packages/redis.md'
      - '.github/workflows/test-redis.yml'
  workflow_call:

jobs:
  test-redis:
    uses: ./.github/workflows/reusable-package-test.yml
    with:
      package_name: "Redis"
      package_slug: "redis"
      package_category: "Database"
      package_language: "c"
      install_commands: |
        [
          "sudo apt-get update",
          "sudo apt-get install -y redis-server"
        ]
      version_command: "redis-server --version | grep -oP '[0-9.]+' | head -1"
      test_commands: |
        [
          {"name": "Check redis-server binary", "command": "command -v redis-server"},
          {"name": "Check redis-cli binary", "command": "command -v redis-cli"},
          {"name": "Get version", "command": "redis-server --version"},
          {"name": "Start server", "command": "timeout 2 redis-server --daemonize yes"}
        ]
```

2. Add to `test-all-packages.yml`
3. Commit and run

**Time:** ~10 minutes

### Method 2: Complex Packages (Advanced)

Use custom workflow for packages requiring:
- Service management (systemctl, etc.)
- HTTP/network testing
- Complex multi-step setup
- Performance benchmarking

**Example:** See `.github/workflows/test-nginx.yml`

**Time:** ~2 hours

### Test Command Best Practices

1. **Start simple:** Binary check, version, help
2. **Add functionality:** Run actual operations
3. **Include cleanup:** Don't leave processes running
4. **Use timeouts:** Prevent hanging tests
5. **Test actual Arm64 functionality:** Not just installation

**Good test progression:**
```yaml
[
  {"name": "Binary exists", "command": "command -v tool"},
  {"name": "Version works", "command": "tool --version"},
  {"name": "Help works", "command": "tool --help | grep -q 'USAGE'"},
  {"name": "Basic operation", "command": "tool process-file input.txt"}
]
```

---

## JSON Schema

### Schema Version 1.0

All test results follow this structure:

```json
{
  "schema_version": "1.0",
  "package": {
    "name": "Package Name",
    "version": "1.2.3",
    "language": "python",
    "category": "Web Server"
  },
  "run": {
    "id": "12345",
    "url": "https://github.com/.../actions/runs/12345",
    "timestamp": "2025-11-17T12:00:00Z",
    "status": "success",
    "runner": {
      "os": "ubuntu-24.04",
      "arch": "arm64"
    }
  },
  "tests": {
    "passed": 5,
    "failed": 0,
    "skipped": 0,
    "duration_seconds": 45,
    "details": [
      {
        "name": "Test description",
        "status": "passed",
        "duration_seconds": 2
      }
    ]
  },
  "metadata": {
    "dashboard_link": "/opensource_packages/package",
    "badge_status": "passing"
  }
}
```

### Field Descriptions

**schema_version:** JSON format version (currently "1.0")

**package:**
- `name` - Display name
- `version` - Detected version from version_command
- `language` - Programming language
- `category` - Package category

**run:**
- `id` - GitHub Actions run ID
- `url` - Link to workflow run
- `timestamp` - ISO 8601 timestamp (UTC)
- `status` - "success" or "failure"
- `runner.os` - Operating system
- `runner.arch` - Architecture (arm64)

**tests:**
- `passed` - Count of passed tests
- `failed` - Count of failed tests
- `skipped` - Count of skipped tests
- `duration_seconds` - Total test duration
- `details` - Array of individual test results

**metadata:**
- `dashboard_link` - Relative URL to package page
- `badge_status` - "passing" or "failing"

---

## Troubleshooting

### Badge Not Displaying

**Problem:** Test results generated but badge doesn't show

**Solution:** Badge only appears in package **expanded view** (click package card to expand)

**Check:**
1. File exists: `data/test-results/<package>.json`
2. File is valid JSON (no syntax errors)
3. Package slug matches file basename (e.g., `nginx.md` → `nginx.json`)
4. Hugo build succeeded (no errors)

### Workflow Failing to Push

**Problem:** `error: failed to push some refs`

**Solution:** Already implemented - auto-retry with rebase

**If still failing:**
1. Check retry count (should be 5 attempts)
2. Check git config is set correctly
3. Verify branch permissions

### Version Detection Failing

**Problem:** `version: unknown` in results

**Solutions:**

1. **Check version command output:**
```bash
# Run locally to see actual output
package --version
```

2. **Adjust parsing:**
```bash
# Simple grep
package --version | grep -oP '[0-9.]+'

# With fallback
package --version 2>&1 | grep -oP 'v\K[0-9.]+' || echo 'unknown'

# Multi-step
package --version | head -1 | awk '{print $2}'
```

### Tests Passing Locally But Failing in CI

**Common causes:**

1. **Package not available on ubuntu-24.04-arm:**
   - Check ARM availability
   - Use binary download instead of apt
   - Try alternative sources (snap, pip, npm)

2. **Version differences:**
   - Test with ubuntu-24.04 specifically
   - Adjust test commands for version differences

3. **Missing dependencies:**
   - Add dependency installation to install_commands
   - Check package documentation for requirements

### JSON Parsing Errors

**Problem:** `unmarshal failed: invalid character`

**Causes:**
1. Missing commas in JSON arrays
2. Unescaped quotes in command strings
3. Incomplete JSON from failed workflow

**Solutions:**
1. Validate JSON locally: `jq . file.json`
2. Use proper JSON escaping in YAML
3. Delete invalid JSON file and re-run workflow

### Hugo Build Errors

**Problem:** `ERROR failed to load data`

**Solution:** 
1. Find and delete invalid JSON files
2. Run `hugo` to verify build succeeds
3. Re-run workflow to regenerate valid JSON

**Prevention:** Workflow only commits valid JSON (always check)

---

## Deployment

### Pre-Deployment Checklist

**Infrastructure:**
- [ ] GitHub Actions workflows tested
- [ ] Badge display working on dashboard
- [ ] JSON schema validated
- [ ] Documentation reviewed

**Quality Checks:**
- [ ] All tests passing (100% success rate)
- [ ] Hugo builds without errors
- [ ] Git conflicts resolve automatically
- [ ] No breaking changes to existing code

**Files to Review:**
- `.github/workflows/test-nginx.yml`
- `.github/workflows/test-envoy.yml`
- `.github/workflows/reusable-package-test.yml`
- `.github/workflows/test-all-packages.yml`
- `themes/.../layouts/partials/package-display/row-sub.html`
- `data/test-results/*.json`

### Deployment Steps

**1. Merge to Main**
```bash
git checkout main
git merge smoke_tests
git push origin main
```

**2. Trigger Initial Run**
- Go to GitHub Actions
- Select "Test All Packages on Arm64"
- Click "Run workflow"
- Select `main` branch
- Click "Run workflow"

**3. Verify Results**
- Monitor workflow execution (~5 min)
- Check all tests pass
- Verify JSON files committed
- Check badges appear on dashboard

**4. Monitor Scheduled Runs**
- First scheduled run: Next day at 2 AM UTC
- Check email/notifications for failures
- Review test results weekly

### Post-Deployment

**Week 1:**
- Monitor daily runs for stability
- Fix any issues that arise
- Add 3-5 high-priority packages

**Month 1:**
- Expand to 10-15 packages
- Gather team feedback
- Optimize test coverage

**Month 3:**
- Cover 20+ priority packages
- Consider advanced features:
  - Performance benchmarking
  - Multi-version testing
  - Trend tracking

### Rollback Plan

If issues arise:

```bash
# Revert merge
git revert -m 1 <merge-commit-hash>
git push origin main

# Or temporarily disable workflows
# Add this to workflow files:
on:
  workflow_dispatch:  # Manual only, remove schedule
```

---

## Advanced Topics

### Custom Workflow Pattern

When you need more control than the reusable template provides:

**Use cases:**
- Service management (systemd, supervisord)
- HTTP/network testing
- Performance benchmarking
- Multi-step complex scenarios

**Example:** `.github/workflows/test-nginx.yml` (341 lines)

**Structure:**
1. Dedicated steps for each test
2. Custom result tracking
3. Detailed error handling
4. Service lifecycle management

### Badge Generation Utility

**Tool:** `build_steps/generate_test_badge.py`

**Usage:**
```bash
# Generate SVG badge
python build_steps/generate_test_badge.py nginx --format svg

# Generate text summary
python build_steps/generate_test_badge.py nginx --format text
```

**Output:**
```
Package: nginx
Version: 1.24.0
Status: passing
Tests: 5 passed, 0 failed
```

### Matrix Testing (Future)

Test multiple versions of the same package:

```yaml
strategy:
  matrix:
    version: ['1.24', '1.25', '1.26']

steps:
  - name: Install nginx ${{ matrix.version }}
    run: |
      sudo apt-get install -y nginx=${{ matrix.version }}.*
```

---

## Reference

### File Locations

```
.github/workflows/
├── test-nginx.yml              # nginx tests (custom)
├── test-envoy.yml              # Envoy tests (reusable)
├── reusable-package-test.yml   # Template workflow
└── test-all-packages.yml       # Orchestrator

data/test-results/
├── nginx.json                  # nginx results
└── envoy.json                  # Envoy results

build_steps/
└── generate_test_badge.py      # Badge utility

themes/arm-design-system-hugo-theme/layouts/
├── shortcodes/test-badge.html              # Shortcode (not used)
└── partials/package-display/row-sub.html   # Badge integration
```

### Workflow Triggers

**Automatic:**
- Daily at 2 AM UTC (test-all-packages.yml)
- On push to main/smoke_tests branches
- On changes to package .md files
- On changes to workflow files

**Manual:**
- GitHub Actions → Select workflow → Run workflow

**Skip CI:**
- Commits with `[skip ci]` are ignored
- Test result commits include `[skip ci]` automatically

### Key Metrics

**Current (2 packages):**
- 100% test pass rate (9/9 tests)
- ~3 min average test duration
- 0 manual interventions required
- 0 Hugo build errors

**Target (20 packages):**
- 95%+ test pass rate
- <60 min total execution (parallel)
- Fully automated
- 100% top priority coverage

---

## Getting Help

**Documentation:**
- This guide (complete reference)
- `SMOKE_TESTS_BRANCH_SUMMARY.md` (detailed technical overview)
- `EXECUTIVE_SUMMARY.md` (quick management summary)
- `ARCHITECTURE_DIAGRAMS.md` (visual diagrams)

**Examples:**
- nginx: Complex custom workflow
- Envoy: Simple reusable workflow
- Both in `.github/workflows/`

**Common Commands:**
```bash
# Test locally
hugo server

# Validate JSON
jq . data/test-results/<package>.json

# Check workflow syntax
cat .github/workflows/test-<package>.yml | yq eval

# View test results
cat data/test-results/<package>.json | jq '.tests'
```

---

*Last Updated: November 17, 2025*  
*Version: 1.0*  
*Status: Production Ready*
