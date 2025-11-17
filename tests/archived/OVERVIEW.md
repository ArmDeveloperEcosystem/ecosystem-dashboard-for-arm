# Functional Testing System for ARM64 Packages

## Overview

This testing system provides automated functional tests for packages in the ecosystem dashboard, running on native ARM64 GitHub runners. The system validates that packages can be installed and run correctly on ARM64 architecture.

## What Was Created

### 1. GitHub Actions Workflow (`test-nginx.yml`)
- **Location**: `.github/workflows/test-nginx.yml`
- **Purpose**: Automated testing workflow for nginx package
- **Features**:
  - Runs on ubuntu-24.04-arm native ARM runners
  - Triggers daily, on content changes, and manually
  - Executes 5 comprehensive tests
  - Generates structured JSON output
  - Commits results to repository
  - Creates GitHub Actions summary

### 2. Test Results Data Structure
- **Location**: `data/test-results/`
- **Files**:
  - `nginx.json` - Test results for nginx (placeholder until first run)
  - `README.md` - Documentation of JSON schema

### 3. Badge Generation Script
- **Location**: `build_steps/generate_test_badge.py`
- **Purpose**: Python utility to generate badges from test results
- **Features**:
  - Reads test result JSON files
  - Generates badge data with colors
  - Creates test summaries
  - Generates SVG badges

### 4. Hugo Shortcode
- **Location**: `themes/arm-design-system-hugo-theme/layouts/shortcodes/test-badge.html`
- **Purpose**: Display test badges on package pages
- **Features**:
  - Shows test status with color coding
  - Links to GitHub Actions run
  - Displays test details in collapsible section
  - Shows last tested timestamp and version

### 5. Documentation
- **Location**: `tests/`
- **Files**:
  - `README.md` - Comprehensive testing framework documentation
  - `QUICKSTART.md` - Step-by-step guide for adding new package tests

## How It Works

### Workflow Execution Flow

```
1. Trigger (daily/manual/push)
   ↓
2. Checkout repository on ARM64 runner
   ↓
3. Install package (nginx via apt)
   ↓
4. Get package version
   ↓
5. Run tests:
   - Check binary exists
   - Check version output
   - Check configuration syntax
   - Start service
   - Test HTTP response
   ↓
6. Calculate test summary
   ↓
7. Generate JSON results
   ↓
8. Upload artifact
   ↓
9. Commit to repository (if main branch)
   ↓
10. Create GitHub Actions summary
```

### JSON Schema

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
    "id": "7234567890",
    "url": "https://github.com/.../actions/runs/...",
    "timestamp": "2025-11-04T02:00:00Z",
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
    "duration_seconds": 8,
    "details": [
      {
        "name": "Check nginx binary",
        "status": "passed",
        "duration_seconds": 1
      }
    ]
  },
  "metadata": {
    "dashboard_link": "/opensource_packages/nginx",
    "badge_status": "passing"
  }
}
```

## Using the System

### Display Test Badge on Package Page

Add to your package markdown file:

```markdown
---
name: NGINX
category: Web Server
# ... other frontmatter
---

{{< test-badge package="nginx" >}}

Package description and content...
```

### Manually Trigger a Test

1. Go to GitHub Actions
2. Select "Test nginx on ARM64" workflow
3. Click "Run workflow"
4. Choose branch and click "Run workflow"

### View Test Results

**In GitHub Actions:**
- Navigate to Actions tab
- Click on the workflow run
- View summary and logs

**On Dashboard:**
- Test badge appears on package page (once Hugo is rebuilt)
- Click badge to see GitHub Actions run
- Expand details to see individual test results

**Via CLI:**
```bash
# Get test summary
python build_steps/generate_test_badge.py nginx summary

# Get badge data
python build_steps/generate_test_badge.py nginx badge

# Generate SVG badge
python build_steps/generate_test_badge.py nginx svg
```

## Adding Tests for New Packages

See `tests/QUICKSTART.md` for detailed step-by-step instructions.

Quick summary:
1. Copy `test-nginx.yml` to `test-<package>.yml`
2. Update package name and installation commands
3. Customize tests for your package
4. Update JSON generation with correct metadata
5. Test the workflow
6. Add badge shortcode to package page

## Test Design Best Practices

### Good Test Characteristics
- ✅ Quick to execute (< 30 seconds total)
- ✅ Tests real ARM64 functionality
- ✅ Clear pass/fail criteria
- ✅ Proper error handling
- ✅ Timing information

### Test Categories
1. **Installation**: Package can be installed
2. **Version**: Version can be retrieved
3. **Configuration**: Configuration is valid
4. **Execution**: Binary/service runs
5. **Functionality**: Basic operations work

### Example Test Patterns

**CLI Tool:**
```yaml
- name: Test CLI execution
  run: |
    if <tool> --version; then
      echo "status=passed" >> $GITHUB_OUTPUT
    else
      echo "status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
```

**Library:**
```yaml
- name: Test library import
  run: |
    if python -c "import <lib>"; then
      echo "status=passed" >> $GITHUB_OUTPUT
    else
      echo "status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
```

**Service:**
```yaml
- name: Test service startup
  run: |
    sudo systemctl start <service>
    if sudo systemctl is-active <service>; then
      echo "status=passed" >> $GITHUB_OUTPUT
    else
      echo "status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
```

## Badge Display

The test badge shows:
- **Green badge**: All tests passing
- **Red badge**: One or more tests failing
- **Gray badge**: No test data or pending

Badge format: `🔧 ARM64 Tests: X passing/failing`

Additional information:
- Last tested timestamp
- Package version
- Expandable test details
- Link to GitHub Actions run

## Maintenance

### Regular Tasks
- Review test failures promptly
- Update tests when packages change
- Archive old test results
- Monitor runner availability

### Troubleshooting
- Check GitHub Actions logs for errors
- Verify ARM runner availability
- Ensure package is available for ARM64
- Review test logic for errors

## Future Enhancements

Potential improvements:
1. **Performance Benchmarks**: Add timing comparisons
2. **Multi-version Testing**: Test multiple package versions
3. **Comparison with x86**: Compare ARM vs x86 performance
4. **Historical Trends**: Track test results over time
5. **Automated Alerts**: Notify on test failures
6. **Coverage Metrics**: Track what percentage of packages have tests

## Technical Details

### Runner Specifications
- OS: Ubuntu 24.04
- Architecture: arm64/aarch64
- Provided by GitHub Actions

### Dependencies
- Python 3 (for badge generation script)
- Hugo (for static site generation)
- Git (for committing results)

### File Permissions
- Workflow needs write permissions to commit results
- Uses `github-actions[bot]` for commits

### Commit Strategy
- Results committed with `[skip ci]` to avoid triggering builds
- Only commits on main branch
- Creates data/test-results/ directory if needed

## Getting Started

1. **Review the nginx workflow**: `.github/workflows/test-nginx.yml`
2. **Read the quickstart guide**: `tests/QUICKSTART.md`
3. **Create your first test**: Follow the quickstart for a new package
4. **Test it**: Manually trigger and verify results
5. **Add badge**: Include shortcode in package markdown
6. **Monitor**: Check results after scheduled runs

## Questions?

Refer to:
- `tests/README.md` - Comprehensive documentation
- `tests/QUICKSTART.md` - Step-by-step guide
- `data/test-results/README.md` - JSON schema details
- Example workflow: `.github/workflows/test-nginx.yml`
