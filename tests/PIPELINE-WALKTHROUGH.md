# Test Results Pipeline Walkthrough

This document walks through the complete pipeline from test execution to badge display.

## Step-by-Step Flow

### 1. GitHub Actions Workflow Executes
**File**: `.github/workflows/test-nginx.yml`

**What happens**:
- Workflow runs on ARM64 runner (`ubuntu-24.04-arm`)
- Installs nginx via `apt-get`
- Runs 5 tests:
  1. Check nginx binary exists
  2. Check nginx version output
  3. Check nginx configuration syntax
  4. Start nginx service
  5. Verify nginx responds to HTTP requests
- Each test records:
  - Status (passed/failed)
  - Duration in seconds

**Triggers**:
- Daily at 2 AM UTC (cron schedule)
- Manual trigger via workflow_dispatch
- On push to main/smoke_tests branches when workflow or nginx.md changes

### 2. Test Results JSON Generated
**Location**: Created in workflow, then committed to `data/test-results/nginx.json`

**Content example**:
```json
{
  "schema_version": "1.0",
  "package": {
    "name": "nginx",
    "version": "1.24.0",
    "language": "c",
    "category": "Web Server"
  },
  "run": {
    "id": "19073848824",
    "url": "https://github.com/ArmDeveloperEcosystem/ecosystem-dashboard-for-arm/actions/runs/19073848824",
    "timestamp": "2025-11-04T15:28:32Z",
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
    "duration_seconds": 6,
    "details": [...]
  },
  "metadata": {
    "dashboard_link": "/opensource_packages/nginx",
    "badge_status": "passing"
  }
}
```

**How it's created**:
- Workflow step "Generate test results JSON" creates the file
- Uses heredoc to write JSON with GitHub Actions variables
- Includes all test results, timing, and metadata

### 3. Results Committed to Repository
**Workflow step**: "Commit test results to repository"

**What happens**:
```bash
git config --global user.name 'github-actions[bot]'
git config --global user.email 'github-actions[bot]@users.noreply.github.com'
mkdir -p data/test-results
cp test-results/nginx.json data/test-results/nginx.json
git add data/test-results/nginx.json
git commit -m "Update nginx test results [skip ci]"
git push
```

**Important notes**:
- Only commits on main or smoke_tests branches
- Uses `[skip ci]` to prevent infinite loop
- Creates directory if it doesn't exist
- Committed by github-actions[bot]

### 4. Hugo Loads Test Results as Data
**Hugo data directory**: `data/test-results/`

**How Hugo uses it**:
- Hugo automatically loads all JSON/YAML/TOML files from `data/` directory
- Makes them available at `.Site.Data.test-results`
- nginx.json becomes `.Site.Data.test-results.nginx`
- **Important**: Don't put .md files in data/ - Hugo can't parse them

### 5. Badge Shortcode Renders the Data
**Shortcode file**: `themes/arm-design-system-hugo-theme/layouts/shortcodes/test-badge.html`

**Usage in content**:
```markdown
---
name: NGINX
# ... frontmatter
---

{{< test-badge package="nginx" >}}
```

**How it works**:
```go-html-template
{{- $package := .Get "package" -}}
{{- $testData := index .Site.Data.test-results $package -}}
{{- if $testData -}}
  <!-- Render badge with test data -->
  <span class="badge badge-{{ $testData.metadata.badge_status }}">
    🔧 ARM64 Tests: {{ $testData.tests.passed }} passing
  </span>
  <!-- Show timestamp, version, expandable details -->
{{- end -}}
```

**Features**:
- Green badge for passing tests
- Red badge for failing tests
- Links to GitHub Actions run
- Shows last test timestamp
- Expandable section with individual test details
- Shows test duration and runner info

### 6. Badge Displays on Package Page
**URL**: `http://localhost:1313/opensource_packages/nginx`

**What you see**:
- ✅ Badge showing "ARM64 Tests: 5 passing"
- 🕒 Last tested timestamp
- 📦 Package version tested
- 📋 Expandable details section with individual test results
- 🔗 Clickable link to GitHub Actions run

## Verification Commands

### Check Test Results JSON
```bash
cat data/test-results/nginx.json | jq
```

### Generate Badge Summary
```bash
python3 build_steps/generate_test_badge.py nginx summary
```

### Get Badge Data
```bash
python3 build_steps/generate_test_badge.py nginx badge
```

### Generate SVG Badge
```bash
python3 build_steps/generate_test_badge.py nginx svg > nginx-badge.svg
```

### View in Browser
```bash
hugo server -D
# Open http://localhost:1313/opensource_packages/nginx
```

## File Locations Summary

| Component | Location | Purpose |
|-----------|----------|---------|
| Workflow | `.github/workflows/test-nginx.yml` | Runs tests on ARM64 |
| Test Results | `data/test-results/nginx.json` | Stores test output |
| Badge Script | `build_steps/generate_test_badge.py` | CLI tool for badges |
| Hugo Shortcode | `themes/.../shortcodes/test-badge.html` | Renders badge |
| Package Content | `content/opensource_packages/nginx.md` | Includes shortcode |
| Documentation | `tests/` | All testing docs |

## Troubleshooting

### Badge Doesn't Show
1. Check JSON file exists: `ls -la data/test-results/nginx.json`
2. Verify JSON is valid: `cat data/test-results/nginx.json | jq`
3. Check shortcode syntax in nginx.md
4. Restart Hugo server
5. Check browser console for errors

### Test Results Don't Update
1. Check workflow ran successfully in GitHub Actions
2. Verify workflow has permission to commit
3. Check that branch is main or smoke_tests
4. Pull latest changes: `git pull`
5. Check commit log: `git log --oneline | head -5`

### Hugo Build Fails
1. Remove any .md files from `data/` directory
2. Only keep .json, .yaml, or .toml files in data/
3. Check Hugo error messages
4. Validate JSON syntax

## Next Steps

1. **Add more package tests**: Copy workflow template for other packages
2. **Customize styling**: Edit shortcode to match site theme
3. **Create summary page**: Show all package test statuses
4. **Add historical data**: Track test results over time
5. **Set up notifications**: Alert on test failures

## Current Status

✅ Workflow runs successfully on ARM64  
✅ All 5 nginx tests passing  
✅ JSON results generated and committed  
✅ Badge displays on package page  
✅ Hugo site renders correctly  
✅ Test details expandable  
✅ Links to GitHub Actions work  

## Pipeline Diagram

```
┌─────────────────────────────────────────┐
│  GitHub Actions (ARM64 Runner)          │
│  - Install nginx                         │
│  - Run 5 tests                           │
│  - Measure timing                        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  Generate JSON                           │
│  test-results/nginx.json                 │
│  - Package metadata                      │
│  - Test results                          │
│  - Run information                       │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  Commit to Repository                    │
│  data/test-results/nginx.json            │
│  - By github-actions[bot]                │
│  - With [skip ci] tag                    │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  Hugo Loads Data                         │
│  .Site.Data.test-results.nginx           │
│  - Parsed as JSON                        │
│  - Available to templates                │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  Shortcode Renders Badge                 │
│  {{< test-badge package="nginx" >}}      │
│  - Reads from .Site.Data                 │
│  - Generates HTML                        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  Badge Displays on Page                  │
│  /opensource_packages/nginx              │
│  - Shows test status                     │
│  - Links to Actions run                  │
│  - Expandable details                    │
└─────────────────────────────────────────┘
```

## Success Metrics

- **Test execution**: ~6 seconds total
- **Workflow runtime**: ~30 seconds including setup
- **All tests passing**: 5/5 ✅
- **Badge status**: passing (green)
- **Hugo build time**: ~320ms
- **Data loaded**: Successfully from data/test-results/
