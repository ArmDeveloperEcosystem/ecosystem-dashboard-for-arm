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
- 3 GitHub Actions workflows (test-nginx, test-envoy, test-all-packages)
- Template file for creating new package tests
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

### Adding a New Package (15-20 minutes)

**Step 1:** Copy the template

```bash
cp .github/workflows/template-package-test.yml .github/workflows/test-redis.yml
```

**Step 2:** Customize `test-redis.yml`

Replace all placeholders:
- `<PACKAGE>` → `Redis` (display name)
- `<package>` → `redis` (lowercase, matches .md filename)

Update the install section:
```yaml
- name: Install Redis
  run: |
    echo "Installing Redis..."
    sudo apt-get update
    sudo apt-get install -y redis-server
    
    if command -v redis-server &> /dev/null; then
      echo "Redis installed successfully"
      echo "install_status=success" >> $GITHUB_OUTPUT
    else
      echo "Redis installation failed"
      echo "install_status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
```

Update version detection:
```yaml
- name: Get Redis version
  id: version
  run: |
    VERSION=$(redis-server --version | grep -oP '[0-9.]+' | head -1 || echo "unknown")
    echo "version=$VERSION" >> $GITHUB_OUTPUT
    echo "Detected Redis version: $VERSION"
```

Add/modify tests as needed (the template has 3 basic tests to start with).

**Step 3:** Add to orchestrator

Edit `.github/workflows/test-all-packages.yml`:

```yaml
jobs:
  test-nginx:
    uses: ./.github/workflows/test-nginx.yml
  
  test-envoy:
    uses: ./.github/workflows/test-envoy.yml
  
  test-redis:  # Add this
    uses: ./.github/workflows/test-redis.yml
  
  summary:
    needs: [test-nginx, test-envoy, test-redis]  # Update this list
```

**Step 4:** Commit and run

```bash
git add .github/workflows/test-redis.yml .github/workflows/test-all-packages.yml
git commit -m "Add Redis functional tests"
git push
```

**Step 5:** Trigger test in GitHub Actions

- Go to Actions → "Test Redis on Arm64" → Run workflow
- Or wait for daily scheduled run (2 AM UTC)

**Step 6:** Verify badge appears

The badge will automatically appear on the Redis package page after the first successful run!

**💡 Pro Tips:**
- Look at `test-nginx.yml` or `test-envoy.yml` for real working examples
- Start with 3-4 basic tests, add more complex ones later
- Template has extensive comments to guide you
- All workflows follow the same pattern - easy to understand and debug

---

## Architecture

### System Components

**Workflows:**
- `template-package-test.yml` - Template for new packages (copy this!)
- `test-nginx.yml` - nginx tests (5 tests, example of complex testing)
- `test-envoy.yml` - Envoy tests (4 tests, example of binary download)
- `test-all-packages.yml` - Orchestrator (runs all tests in parallel)

**Data:
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

```

### Workflow Pattern

**Single Pattern:** Copy the template and customize

```
template-package-test.yml  →  Copy to test-<package>.yml  →  Customize  →  Results
```

All workflows follow the same structure:
1. **Install** - Download/install the package
2. **Version** - Detect package version
3. **Test** - Run functional tests (3-10 tests typical)
4. **JSON** - Generate test results in schema v1.0
5. **Commit** - Auto-commit results with conflict resolution
6. **Summary** - Display results in GitHub Actions

**Examples:**
- `test-nginx.yml` - Comprehensive example with 5 tests, service management, HTTP testing
- `test-envoy.yml` - Binary download example with 4 tests
- `template-package-test.yml` - Heavily commented template to copy

**Time to add:** 15-20 minutes per package

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

The badge system uses **direct template integration** in the Hugo theme:

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

- **Template-based**: Badge integration is handled entirely in the `row-sub.html` template
- **No shortcodes used**: The dashboard doesn't use Hugo shortcodes for badges because it doesn't render individual package pages
- **No manual setup**: Badges appear automatically when JSON test results exist - no changes needed to package markdown files

**Viewing Badges:**

1. Start Hugo: `hugo server -D`
2. Open: http://localhost:1313/
3. Search for or scroll to the package (e.g., "nginx")
4. Click the package card to expand it
5. Badge appears in the expanded section with test details

**Direct Link Pattern:**
- http://localhost:1313/?package=nginx (auto-expands nginx)

---

## Adding New Packages

### The Template Approach

All packages follow the same pattern: **copy the template and customize**.

**Step-by-Step Example: Adding Redis**

**1. Copy the template:**

```bash
cp .github/workflows/template-package-test.yml .github/workflows/test-redis.yml
```

**2. Customize the workflow:**

Open `test-redis.yml` and make these changes:

a) **Update the header:**
```yaml
name: Test Redis on Arm64  # Change from <PACKAGE>

on:
  workflow_dispatch:
  workflow_call:
  push:
    branches: [main, smoke_tests]
    paths:
      - 'content/opensource_packages/redis.md'  # Change from <package>
      - '.github/workflows/test-redis.yml'       # Change from <package>

jobs:
  test-redis:  # Change from test-<package>
    runs-on: ubuntu-24.04-arm
```

b) **Update metadata:**
```yaml
- name: Set test metadata
  id: metadata
  run: |
    echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $GITHUB_OUTPUT
    echo "package_slug=redis" >> $GITHUB_OUTPUT  # Change from <package>
    echo "dashboard_link=/opensource_packages/redis" >> $GITHUB_OUTPUT
```

c) **Customize installation:**
```yaml
- name: Install Redis  # Change from <PACKAGE>
  id: install
  run: |
    echo "Installing Redis..."
    sudo apt-get update
    sudo apt-get install -y redis-server
    
    if command -v redis-server &> /dev/null; then
      echo "Redis installed successfully"
      echo "install_status=success" >> $GITHUB_OUTPUT
    else
      echo "Redis installation failed"
      echo "install_status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
```

d) **Update version detection:**
```yaml
- name: Get Redis version
  id: version
  run: |
    VERSION=$(redis-server --version | grep -oP '[0-9.]+' | head -1 || echo "unknown")
    echo "version=$VERSION" >> $GITHUB_OUTPUT
    echo "Detected Redis version: $VERSION"
```

e) **Customize tests** (the template has 3 basic tests - modify as needed):
```yaml
- name: Test 1 - Check redis-server binary exists
  id: test1
  run: |
    START_TIME=$(date +%s)
    
    if command -v redis-server &> /dev/null; then
      echo "✓ redis-server binary found"
      echo "status=passed" >> $GITHUB_OUTPUT
    else
      echo "✗ redis-server binary not found"
      echo "status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
    
    END_TIME=$(date +%s)
    echo "duration=$((END_TIME - START_TIME))" >> $GITHUB_OUTPUT

- name: Test 2 - Check redis-cli binary exists
  id: test2
  run: |
    START_TIME=$(date +%s)
    
    if command -v redis-cli &> /dev/null; then
      echo "✓ redis-cli binary found"
      echo "status=passed" >> $GITHUB_OUTPUT
    else
      echo "✗ redis-cli binary not found"
      echo "status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
    
    END_TIME=$(date +%s)
    echo "duration=$((END_TIME - START_TIME))" >> $GITHUB_OUTPUT

# Add more tests as needed (test3, test4, etc.)
```

f) **Update JSON generation** (update package metadata and test details list):
```yaml
- name: Generate test results JSON
  if: always()
  run: |
    mkdir -p test-results
    
    cat > test-results/redis.json << EOF
    {
      "schema_version": "1.0",
      "package": {
        "name": "Redis",
        "version": "${{ steps.version.outputs.version }}",
        "language": "c",
        "category": "Database"
      },
      "run": {
        ...
      },
      "tests": {
        "passed": ${{ steps.summary.outputs.passed }},
        "failed": ${{ steps.summary.outputs.failed }},
        "skipped": 0,
        "duration_seconds": ${{ steps.summary.outputs.duration }},
        "details": [
          {
            "name": "Check redis-server binary exists",
            "status": "${{ steps.test1.outputs.status }}",
            "duration_seconds": ${{ steps.test1.outputs.duration || 0 }}
          },
          {
            "name": "Check redis-cli binary exists",
            "status": "${{ steps.test2.outputs.status }}",
            "duration_seconds": ${{ steps.test2.outputs.duration || 0 }}
          }
        ]
      },
      ...
    }
    EOF
```

**3. Add to orchestrator:**

Edit `.github/workflows/test-all-packages.yml`:

```yaml
jobs:
  test-nginx:
    uses: ./.github/workflows/test-nginx.yml
  
  test-envoy:
    uses: ./.github/workflows/test-envoy.yml
  
  test-redis:  # Add this
    uses: ./.github/workflows/test-redis.yml
  
  summary:
    needs: [test-nginx, test-envoy, test-redis]  # Add redis to the list
```

**4. Commit and test:**

```bash
git add .github/workflows/test-redis.yml .github/workflows/test-all-packages.yml
git commit -m "Add Redis functional tests"
git push
```

**5. Run the test:**
- GitHub Actions → "Test Redis on Arm64" → Run workflow
- Or wait for daily scheduled run

**Time:** 15-20 minutes

### Examples to Learn From

**Simple package (apt install):**
- Look at `test-nginx.yml` - Shows comprehensive testing with 5 tests
- Includes service management, HTTP testing, systemctl

**Binary download:**
- Look at `test-envoy.yml` - Shows how to download and install a binary
- 4 simple tests checking binary functionality

**Template:**
- `template-package-test.yml` - Heavily commented, shows all the patterns

### Common Customizations

**For services (like nginx, redis):**
```yaml
- name: Test - Start Redis service
  id: test3
  run: |
    START_TIME=$(date +%s)
    
    sudo systemctl start redis-server
    sleep 2
    
    if sudo systemctl is-active redis-server; then
      echo "✓ Redis service is active"
      echo "status=passed" >> $GITHUB_OUTPUT
    else
      echo "✗ Redis service failed to start"
      echo "status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
    
    END_TIME=$(date +%s)
    echo "duration=$((END_TIME - START_TIME))" >> $GITHUB_OUTPUT
```

**For network testing:**
```yaml
- name: Test - HTTP response
  id: test4
  run: |
    START_TIME=$(date +%s)
    
    # Start redis-server in background
    redis-server --port 6379 --daemonize yes
    sleep 2
    
    # Test connection
    if redis-cli ping | grep -q "PONG"; then
      echo "✓ Redis responding to ping"
      echo "status=passed" >> $GITHUB_OUTPUT
    else
      echo "✗ Redis not responding"
      echo "status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
    
    END_TIME=$(date +%s)
    echo "duration=$((END_TIME - START_TIME))" >> $GITHUB_OUTPUT
```

**For binary downloads (like Envoy):**
```yaml
- name: Install Envoy
  id: install
  run: |
    echo "Installing Envoy..."
    
    # Download official ARM64 binary
    ENVOY_VERSION="v1.32.3"
    wget https://github.com/envoyproxy/envoy/releases/download/${ENVOY_VERSION}/envoy-${ENVOY_VERSION}-linux-aarch64
    
    # Install to /usr/local/bin
    sudo mv envoy-${ENVOY_VERSION}-linux-aarch64 /usr/local/bin/envoy
    sudo chmod +x /usr/local/bin/envoy
    
    if command -v envoy &> /dev/null; then
      echo "Envoy installed successfully"
      echo "install_status=success" >> $GITHUB_OUTPUT
    else
      echo "Envoy installation failed"
      echo "install_status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
```

**For complex version detection:**
```yaml
- name: Get package version
  id: version
  run: |
    # Try multiple methods
    VERSION=$(nginx -v 2>&1 | grep -oP '[0-9.]+' | head -1 || echo "unknown")
    
    # Or parse from config
    VERSION=$(python3 --version 2>&1 | awk '{print $2}' || echo "unknown")
    
    # Or from package manager
    VERSION=$(dpkg -s nginx | grep '^Version:' | awk '{print $2}' || echo "unknown")
    
    echo "version=$VERSION" >> $GITHUB_OUTPUT
    echo "Detected version: $VERSION"
```

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
- `.github/workflows/template-package-test.yml`
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

### Customizing the Template

The template provides a flexible starting point for all package types:

**Common customizations:**
- **Service management:** systemd, supervisord, etc.
- **HTTP/network testing:** curl, wget, connection tests
- **Performance benchmarking:** timing tests, load tests
- **Multi-step scenarios:** Complex setup/teardown

**Example of comprehensive testing:** See `.github/workflows/test-nginx.yml` (370 lines)
- Shows 5 different test types
- Service lifecycle management
- HTTP response testing
- Detailed error handling

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
├── test-nginx.yml              # nginx tests (370 lines, 5 tests)
├── test-envoy.yml              # Envoy tests (295 lines, 4 tests)
├── template-package-test.yml   # Template file for new packages
└── test-all-packages.yml       # Orchestrator (runs all tests daily)

data/test-results/
├── nginx.json                  # nginx results
└── envoy.json                  # Envoy results

themes/arm-design-system-hugo-theme/layouts/
└── partials/package-display/row-sub.html   # Badge display template
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

**Example Workflows:**
- `test-nginx.yml` - Comprehensive testing with 5 tests, service management
- `test-envoy.yml` - Binary download and basic functionality tests
- `template-package-test.yml` - Copy this template for new packages

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
