# Scalable Testing Architecture

## Overview

The testing system uses a three-tier architecture for maximum flexibility and scalability:

1. **Parent Orchestrator** (`test-all-packages.yml`) - Runs all package tests
2. **Reusable Workflow** (`reusable-package-test.yml`) - Generic test template
3. **Individual Package Workflows** - Package-specific configurations

## Architecture Diagram

```
┌─────────────────────────────────────────────┐
│   test-all-packages.yml (Parent)            │
│   - Triggers all package tests              │
│   - Runs on schedule/manual/push            │
│   - Generates summary report                │
└────────────┬────────────────────────────────┘
             │
             ├──────────────┬──────────────┬─────────────
             │              │              │
             ▼              ▼              ▼
    ┌────────────────┐ ┌────────────┐ ┌────────────┐
    │  test-nginx    │ │ test-envoy │ │  test-*    │
    │  .yml          │ │ .yml       │ │  .yml      │
    │  (Custom)      │ │ (Reusable) │ │ (Reusable) │
    └────────┬───────┘ └──────┬─────┘ └──────┬─────┘
             │                │                │
             │                └────────┬───────┘
             │                         │
             ▼                         ▼
    ┌────────────────┐      ┌──────────────────────┐
    │ Custom test    │      │ reusable-package-    │
    │ logic for      │      │ test.yml             │
    │ nginx          │      │ - Generic test logic │
    └────────────────┘      │ - JSON config driven │
                            └──────────────────────┘
```

## File Structure

```
.github/workflows/
├── test-all-packages.yml      # Parent orchestrator
├── reusable-package-test.yml  # Generic reusable template
├── test-nginx.yml             # nginx-specific (custom)
├── test-envoy.yml             # envoy-specific (uses reusable)
└── test-*.yml                 # Additional package tests
```

## Workflow Types

### Type 1: Custom Workflow (nginx)

Best for packages with complex, unique test requirements.

**Pros:**
- Full control over test logic
- Can handle complex scenarios
- Custom error handling

**Cons:**
- More code duplication
- Harder to maintain at scale

**Example:** `test-nginx.yml`

### Type 2: Reusable Workflow (envoy, future packages)

Best for packages with standard test patterns.

**Pros:**
- Minimal code duplication
- Easy to add new packages
- Consistent test structure
- Centralized updates

**Cons:**
- Less flexibility
- JSON configuration can be verbose

**Example:** `test-envoy.yml` calling `reusable-package-test.yml`

## Adding a New Package Test

### Option A: Using Reusable Workflow (Recommended)

1. **Create workflow file**: `.github/workflows/test-<package>.yml`

```yaml
name: Test <Package> on ARM64

on:
  workflow_dispatch:
  push:
    branches: [main, smoke_tests]
    paths:
      - 'content/opensource_packages/<package>.md'
      - '.github/workflows/test-<package>.yml'
  workflow_call:

jobs:
  test-<package>:
    uses: ./.github/workflows/reusable-package-test.yml
    with:
      package_name: "<Package Name>"
      package_slug: "<package-slug>"
      package_category: "<Category>"
      package_language: "<language>"
      install_commands: |
        [
          "sudo apt-get update",
          "sudo apt-get install -y <package>"
        ]
      version_command: "<package> --version | grep -oP '[0-9.]+' | head -1"
      test_commands: |
        [
          {
            "name": "Check binary",
            "command": "command -v <package>"
          },
          {
            "name": "Check version",
            "command": "<package> --version"
          }
        ]
```

2. **Add to parent workflow**: Edit `test-all-packages.yml`

```yaml
jobs:
  # ... existing jobs
  
  test-<package>:
    uses: ./.github/workflows/test-<package>.yml
```

3. **Update summary job**: Add to `needs` array

```yaml
summary:
  needs: [test-nginx, test-envoy, test-<package>]
```

### Option B: Custom Workflow

Copy `test-nginx.yml` and customize for your package.

## Reusable Workflow Parameters

### Inputs

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `package_name` | string | Display name | "Envoy" |
| `package_slug` | string | Filename (no .md) | "envoy" |
| `package_category` | string | Package category | "Proxy" |
| `package_language` | string | Programming language | "c++" |
| `install_commands` | JSON array | Installation commands | See below |
| `version_command` | string | Command to get version | "envoy --version" |
| `test_commands` | JSON array | Test configurations | See below |

### install_commands Format

JSON array of shell commands to execute sequentially:

```json
[
  "sudo apt-get update",
  "sudo apt-get install -y package-name",
  "command-to-verify-installation"
]
```

**Tips:**
- Each command is executed independently
- Use `||` for fallback options
- Commands run in order
- Failed commands stop execution

### test_commands Format

JSON array of test objects:

```json
[
  {
    "name": "Descriptive test name",
    "command": "shell command that returns 0 for success"
  },
  {
    "name": "Another test",
    "command": "another command"
  }
]
```

**Test Object:**
- `name`: Human-readable test description
- `command`: Shell command (0 = pass, non-zero = fail)

**Tips:**
- Use `command -v` to check binary exists
- Use `grep -q` for silent pattern matching
- Chain commands with `&&` for multi-step tests
- Redirect output as needed

## Running Tests

### Run All Packages

```bash
# Via GitHub UI
Actions → Test All Packages on ARM64 → Run workflow

# Via GitHub CLI (if installed)
gh workflow run test-all-packages.yml
```

### Run Individual Package

```bash
# Via GitHub UI
Actions → Test <Package> on ARM64 → Run workflow

# Via push trigger
git commit -m "Update envoy.md"
git push
```

### Scheduled Runs

All packages run daily at 2 AM UTC via the parent workflow.

## Test Results

### JSON Output

Each test generates: `data/test-results/<package-slug>.json`

### Artifacts

- Individual: `<package>-test-results` (90 days retention)
- All tests: Available in parent workflow run

### Badge Display

Badges automatically appear for any package with test results:
1. Test data in `data/test-results/<package>.json`
2. Badge shows in expanded package row
3. No template changes needed

## Example Workflows

### Simple CLI Tool

```yaml
test-mycli:
  uses: ./.github/workflows/reusable-package-test.yml
  with:
    package_name: "MyCLI"
    package_slug: "mycli"
    package_category: "CLI Tools"
    package_language: "go"
    install_commands: |
      [
        "wget https://github.com/user/mycli/releases/download/v1.0.0/mycli-linux-arm64",
        "sudo mv mycli-linux-arm64 /usr/local/bin/mycli",
        "sudo chmod +x /usr/local/bin/mycli"
      ]
    version_command: "mycli version | grep -oP '[0-9.]+'"
    test_commands: |
      [
        {"name": "Check binary", "command": "command -v mycli"},
        {"name": "Run help", "command": "mycli --help"},
        {"name": "Version check", "command": "mycli version"}
      ]
```

### Python Package

```yaml
test-numpy:
  uses: ./.github/workflows/reusable-package-test.yml
  with:
    package_name: "NumPy"
    package_slug: "numpy"
    package_category: "Scientific Computing"
    package_language: "python"
    install_commands: |
      [
        "sudo apt-get update",
        "sudo apt-get install -y python3-pip",
        "pip3 install numpy"
      ]
    version_command: "python3 -c 'import numpy; print(numpy.__version__)'"
    test_commands: |
      [
        {"name": "Import test", "command": "python3 -c 'import numpy'"},
        {"name": "Basic operation", "command": "python3 -c 'import numpy; a=numpy.array([1,2,3]); print(a.sum())'"},
        {"name": "ARM optimization check", "command": "python3 -c 'import numpy; print(numpy.show_config())'"}
      ]
```

### Docker-based Tool

```yaml
test-docker-app:
  uses: ./.github/workflows/reusable-package-test.yml
  with:
    package_name: "MyDockerApp"
    package_slug: "mydockerapp"
    package_category: "Containers"
    package_language: "docker"
    install_commands: |
      [
        "docker pull myorg/myapp:latest-arm64"
      ]
    version_command: "docker run --rm myorg/myapp:latest-arm64 --version | grep -oP '[0-9.]+'"
    test_commands: |
      [
        {"name": "Pull image", "command": "docker images | grep myapp"},
        {"name": "Run help", "command": "docker run --rm myorg/myapp:latest-arm64 --help"},
        {"name": "Basic execution", "command": "docker run --rm myorg/myapp:latest-arm64 test-command"}
      ]
```

## Best Practices

### 1. Test Design
- Keep tests simple and fast (< 1 minute total)
- Test actual ARM64 functionality, not just installation
- Use meaningful test names
- Test in order of complexity (binary → version → functionality)

### 2. Installation Commands
- Always start with `sudo apt-get update` if using apt
- Provide fallback options with `||`
- Verify installation succeeded
- Clean up temporary files

### 3. Version Detection
- Extract only the version number
- Handle different output formats
- Use `|| echo "unknown"` as fallback

### 4. Error Handling
- Use silent grep (`grep -q`) when appropriate
- Redirect stderr when needed (`2>&1`)
- Provide informative error messages

### 5. Maintenance
- Review test failures promptly
- Update version commands as packages evolve
- Keep installation methods current
- Document any special requirements

## Scaling Considerations

### Current Capacity
- 2 packages (nginx, envoy)
- ~30-60 seconds per package
- Total ~2-5 minutes for all tests

### Adding More Packages
- Up to ~20 packages: Use reusable workflow
- 20-50 packages: Consider matrix strategy
- 50+ packages: Split into multiple parent workflows

### Performance Tips
- Run tests in parallel (default behavior)
- Use caching for repeated dependencies
- Minimize external downloads
- Keep test count reasonable (3-5 tests per package)

## Troubleshooting

### Workflow Not Triggering
- Check branch name matches triggers
- Verify file paths in `on.push.paths`
- Ensure `workflow_call` is present for sub-workflows

### JSON Parsing Errors
- Validate JSON syntax in parameters
- Escape quotes properly in commands
- Use single quotes for outer JSON, double inside

### Test Failures
- Check GitHub Actions logs
- Verify package availability for ARM64
- Test installation commands locally if possible
- Review version command output

### Badge Not Showing
- Ensure JSON file is committed
- Check package slug matches filename
- Verify JSON is valid
- Restart Hugo server

## Future Enhancements

Potential improvements:
- Matrix strategy for multi-version testing
- Conditional tests based on package type
- Performance benchmarking
- Comparison with x86_64
- Automatic PR creation on test failures
- Integration with package update notifications
- Test coverage metrics dashboard
