# Quick Start: Adding Tests for a New Package

This guide walks you through adding functional tests for a package on ARM64.

## Prerequisites

- Package is listed in `content/opensource_packages/` or `content/commercial_packages/`
- GitHub Actions with ARM runners enabled
- Basic understanding of package installation and testing

## Steps

### 1. Copy the Template Workflow

```bash
# Copy the nginx workflow as a template
cp .github/workflows/test-nginx.yml .github/workflows/test-<your-package>.yml
```

### 2. Customize the Workflow

Edit `.github/workflows/test-<your-package>.yml`:

**Update the workflow name:**
```yaml
name: Test <your-package> on ARM64
```

**Update the trigger paths:**
```yaml
on:
  # ... other triggers
  push:
    paths:
      - 'content/opensource_packages/<your-package>.md'  # or commercial_packages
      - '.github/workflows/test-<your-package>.yml'
```

**Update metadata:**
```yaml
- name: Set test metadata
  id: metadata
  run: |
    echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $GITHUB_OUTPUT
    echo "package_slug=<your-package>" >> $GITHUB_OUTPUT
    echo "dashboard_link=/opensource_packages/<your-package>" >> $GITHUB_OUTPUT
```

### 3. Customize Installation Steps

Replace the nginx installation with your package's installation:

```yaml
- name: Install <your-package>
  id: install
  run: |
    echo "Installing <your-package>..."
    # For apt packages:
    sudo apt-get update
    sudo apt-get install -y <your-package>
    
    # For pip packages:
    # pip install <your-package>
    
    # For npm packages:
    # npm install -g <your-package>
    
    # Verify installation
    if command -v <your-command> &> /dev/null; then
      echo "install_status=success" >> $GITHUB_OUTPUT
    else
      echo "install_status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
```

### 4. Customize Version Detection

Update the version detection for your package:

```yaml
- name: Get <your-package> version
  id: version
  run: |
    # Adjust the command based on your package
    VERSION=$(<your-command> --version | grep -oP 'version\s+\K[0-9.]+' || echo "unknown")
    echo "version=$VERSION" >> $GITHUB_OUTPUT
    echo "Detected version: $VERSION"
```

### 5. Create Package-Specific Tests

Replace the nginx tests with tests appropriate for your package. Each test should:
- Have a unique ID (test1, test2, etc.)
- Record start/end time
- Output status (passed/failed)
- Exit with code 1 on failure

Example test template:
```yaml
- name: Test X - Description
  id: testX
  run: |
    START_TIME=$(date +%s)
    
    # Your test logic here
    if <test-condition>; then
      echo "✓ Test passed"
      echo "status=passed" >> $GITHUB_OUTPUT
    else
      echo "✗ Test failed"
      echo "status=failed" >> $GITHUB_OUTPUT
      exit 1
    fi
    
    END_TIME=$(date +%s)
    echo "duration=$((END_TIME - START_TIME))" >> $GITHUB_OUTPUT
```

### 6. Update Test Summary Calculation

If you change the number of tests, update the summary calculation step:

```yaml
- name: Calculate test summary
  if: always()
  id: summary
  run: |
    PASSED=0
    FAILED=0
    TOTAL_DURATION=0
    
    # Add a block for each test
    if [ "${{ steps.test1.outputs.status }}" == "passed" ]; then
      PASSED=$((PASSED + 1))
    else
      FAILED=$((FAILED + 1))
    fi
    TOTAL_DURATION=$((TOTAL_DURATION + ${{ steps.test1.outputs.duration || 0 }}))
    
    # ... repeat for test2, test3, etc.
    
    # Final status
    echo "passed=$PASSED" >> $GITHUB_OUTPUT
    echo "failed=$FAILED" >> $GITHUB_OUTPUT
    echo "duration=$TOTAL_DURATION" >> $GITHUB_OUTPUT
    
    if [ $FAILED -eq 0 ]; then
      echo "overall_status=success" >> $GITHUB_OUTPUT
      echo "badge_status=passing" >> $GITHUB_OUTPUT
    else
      echo "overall_status=failure" >> $GITHUB_OUTPUT
      echo "badge_status=failing" >> $GITHUB_OUTPUT
    fi
```

### 7. Update JSON Generation

Modify the JSON generation to reflect your package details:

```yaml
- name: Generate test results JSON
  if: always()
  run: |
    mkdir -p test-results
    
    cat > test-results/<your-package>.json << EOF
    {
      "schema_version": "1.0",
      "package": {
        "name": "<your-package>",
        "version": "${{ steps.version.outputs.version }}",
        "language": "<language>",  # e.g., "python", "go", "c", "javascript"
        "category": "<category>"    # e.g., "Database", "Web Server", "ML Framework"
      },
      "run": {
        "id": "${{ github.run_id }}",
        "url": "${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}",
        "timestamp": "${{ steps.metadata.outputs.timestamp }}",
        "status": "${{ steps.summary.outputs.overall_status }}",
        "runner": {
          "os": "ubuntu-24.04",
          "arch": "arm64"
        }
      },
      "tests": {
        "passed": ${{ steps.summary.outputs.passed }},
        "failed": ${{ steps.summary.outputs.failed }},
        "skipped": 0,
        "duration_seconds": ${{ steps.summary.outputs.duration }},
        "details": [
          {
            "name": "Test 1 description",
            "status": "${{ steps.test1.outputs.status }}",
            "duration_seconds": ${{ steps.test1.outputs.duration || 0 }}
          }
          # Add entries for all tests
        ]
      },
      "metadata": {
        "dashboard_link": "${{ steps.metadata.outputs.dashboard_link }}",
        "badge_status": "${{ steps.summary.outputs.badge_status }}"
      }
    }
    EOF
```

### 8. Update Artifact Names

```yaml
- name: Upload test results
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: <your-package>-test-results
    path: test-results/<your-package>.json
    retention-days: 90

- name: Commit test results to repository
  if: always() && github.ref == 'refs/heads/main'
  run: |
    # ...
    cp test-results/<your-package>.json data/test-results/<your-package>.json
    git add data/test-results/<your-package>.json
    git diff --staged --quiet || git commit -m "Update <your-package> test results [skip ci]"
    # ...
```

### 9. Test Your Workflow

1. Commit the workflow file
2. Manually trigger it from GitHub Actions UI
3. Review the output and fix any issues
4. Verify the JSON file is generated correctly

### 10. Add Badge to Package Page

Edit your package markdown file (e.g., `content/opensource_packages/<your-package>.md`):

```markdown
---
name: Your Package
category: Category
description: Description...
# ... other frontmatter
---

{{< test-badge package="<your-package>" >}}

Additional package content...
```

## Common Test Patterns

### Python Packages

```yaml
- name: Install package
  run: |
    pip install <package>
    
- name: Test import
  run: |
    python -c "import <package>; print(<package>.__version__)"
    
- name: Run basic operation
  run: |
    python -c "import <package>; <package>.some_function()"
```

### Node.js Packages

```yaml
- name: Install package
  run: |
    npm install -g <package>
    
- name: Test CLI
  run: |
    <package> --version
    
- name: Run basic command
  run: |
    <package> <test-command>
```

### Go Packages

```yaml
- name: Install package
  run: |
    go install <package>@latest
    
- name: Test binary
  run: |
    <binary-name> version
    
- name: Run test
  run: |
    <binary-name> <test-command>
```

### System Services

```yaml
- name: Start service
  run: |
    sudo systemctl start <service>
    
- name: Check service status
  run: |
    sudo systemctl is-active <service>
    
- name: Test functionality
  run: |
    # Service-specific test (e.g., HTTP request, database query)
```

## Troubleshooting

**Workflow doesn't trigger:**
- Check the file path in the trigger configuration
- Ensure the workflow file is in `.github/workflows/`
- Verify branch protection rules

**Tests fail on ARM but work locally:**
- Check ARM-specific dependencies
- Verify package availability for ARM64
- Review runner OS version compatibility

**JSON generation fails:**
- Check for syntax errors in the heredoc
- Ensure all variables are properly escaped
- Verify all referenced step outputs exist

**Badge doesn't appear:**
- Ensure JSON file is committed to `data/test-results/`
- Check Hugo shortcode syntax
- Verify package name matches exactly

## Next Steps

- Add more comprehensive tests
- Set up notifications for test failures
- Create tests for related packages
- Review test results regularly
