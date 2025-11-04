# Package Testing Framework

This directory contains the infrastructure for automated functional testing of packages listed in the ecosystem dashboard.

## Overview

The testing framework provides:
- Automated testing of packages on ARM64 architecture
- GitHub Actions workflows that run on native ARM runners
- Standardized JSON output for test results
- Badge generation for displaying test status on package pages
- Integration with the Hugo-based dashboard

## Directory Structure

```
.github/workflows/
  test-nginx.yml          # Example workflow for nginx
  test-*.yml              # Additional package test workflows

build_steps/
  generate_test_badge.py  # Script to generate badges from test results

data/test-results/
  nginx.json              # Test results for nginx
  *.json                  # Test results for other packages
  README.md               # Test results documentation
```

## Creating a New Package Test

### 1. Create a GitHub Actions Workflow

Create `.github/workflows/test-<package-name>.yml` based on the nginx template:

```yaml
name: Test <package-name> on ARM64

on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM UTC
  workflow_dispatch:
  push:
    branches:
      - main
    paths:
      - 'content/opensource_packages/<package-name>.md'
      - '.github/workflows/test-<package-name>.yml'

jobs:
  test-<package-name>:
    runs-on: ubuntu-24.04-arm
    
    steps:
      # ... (see nginx workflow for full template)
```

### 2. Define Package-Specific Tests

Each workflow should include tests that:
1. Install the package
2. Verify the installation
3. Run basic functionality tests
4. Generate structured output

Example test steps:
```yaml
- name: Test 1 - Check binary exists
  id: test1
  run: |
    START_TIME=$(date +%s)
    if command -v <package-binary> &> /dev/null; then
      echo "status=passed" >> $GITHUB_OUTPUT
    else
      echo "status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
    END_TIME=$(date +%s)
    echo "duration=$((END_TIME - START_TIME))" >> $GITHUB_OUTPUT
```

### 3. Generate Test Results JSON

The workflow automatically generates a JSON file with the following structure:

```json
{
  "schema_version": "1.0",
  "package": {
    "name": "package-name",
    "version": "x.y.z",
    "language": "language",
    "category": "category"
  },
  "run": {
    "id": "github-run-id",
    "url": "https://github.com/...",
    "timestamp": "2025-11-03T14:30:00Z",
    "status": "success|failure",
    "runner": {
      "os": "ubuntu-24.04",
      "arch": "arm64"
    }
  },
  "tests": {
    "passed": 5,
    "failed": 0,
    "skipped": 0,
    "duration_seconds": 10,
    "details": [
      {
        "name": "Test name",
        "status": "passed|failed|skipped",
        "duration_seconds": 2
      }
    ]
  },
  "metadata": {
    "dashboard_link": "/opensource_packages/package-name",
    "badge_status": "passing|failing"
  }
}
```

## Test Result Integration

### Displaying Badges

Use the `generate_test_badge.py` script to create badges:

```bash
# Get badge data as JSON
python build_steps/generate_test_badge.py nginx badge

# Get test summary
python build_steps/generate_test_badge.py nginx summary

# Generate SVG badge
python build_steps/generate_test_badge.py nginx svg
```

### Hugo Integration

To display test results on package pages, you can:

1. **Add a shortcode** in `themes/arm-design-system-hugo-theme/layouts/shortcodes/test-badge.html`:

```html
{{ $package := .Get "package" }}
{{ $testData := index .Site.Data.test-results $package }}
{{ if $testData }}
  <div class="test-badge">
    <a href="{{ $testData.run.url }}" target="_blank">
      <span class="badge badge-{{ $testData.metadata.badge_status }}">
        ARM64 Tests: {{ $testData.tests.passed }} passed, {{ $testData.tests.failed }} failed
      </span>
    </a>
    <small>Last run: {{ $testData.run.timestamp }}</small>
  </div>
{{ end }}
```

2. **Use in package markdown**:

```markdown
---
name: nginx
# ... other frontmatter
---

{{< test-badge package="nginx" >}}
```

## Workflow Triggers

Tests run automatically:
- **Scheduled**: Daily at 2 AM UTC
- **On push**: When package content or workflow changes
- **Manual**: Via GitHub Actions UI

## Best Practices

### Test Design

1. **Keep tests simple and fast**: Focus on basic functionality
2. **Test actual ARM64 execution**: Don't just check installation
3. **Use proper error handling**: Capture failures gracefully
4. **Record timing**: Track test duration for performance insights

### Test Categories

Recommended test types:
- Binary/executable verification
- Version checking
- Configuration validation
- Service startup
- Basic functionality (HTTP request, simple computation, etc.)

### Maintenance

- Review test failures promptly
- Update tests when package behavior changes
- Archive old test results periodically
- Monitor test execution time

## Example: nginx Tests

The nginx workflow includes these tests:

1. **Check nginx binary**: Verifies nginx command is available
2. **Check nginx version output**: Validates version command works
3. **Check nginx configuration syntax**: Tests config file is valid
4. **Start nginx service**: Starts the nginx systemd service
5. **Verify nginx responds to HTTP requests**: Makes HTTP request to localhost

## Troubleshooting

### Test Failures

1. Check the GitHub Actions run log
2. Review the test results JSON
3. Manually trigger the workflow for debugging
4. Verify ARM runner availability

### Missing Test Results

1. Ensure workflow has proper permissions
2. Check if workflow is triggered correctly
3. Verify JSON generation step succeeds
4. Check git commit/push permissions

## Future Enhancements

Potential improvements:
- Performance benchmarking
- Multi-version testing
- Comparison with x86_64 results
- Historical trend tracking
- Automated issue creation on failures
- Integration with package update notifications
