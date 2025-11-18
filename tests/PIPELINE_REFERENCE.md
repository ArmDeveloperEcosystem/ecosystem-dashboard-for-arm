# Pipeline Reference - Technical Deep Dive

**Navigation:**
- [README](README.md) - Quick start
- [Complete Guide](COMPLETE_GUIDE.md) - Main documentation
- This document - Advanced topics

---

## Table of Contents

- [Pipeline Flow](#pipeline-flow)
- [Advanced Customization](#advanced-customization)
- [Performance Optimization](#performance-optimization)
- [Debugging](#debugging)
- [Complex Scenarios](#complex-scenarios)
- [Best Practices](#best-practices)

---

## Pipeline Flow

### Detailed Execution Sequence

```
1. Workflow Trigger
   ├─ Scheduled (daily 2 AM UTC)
   ├─ Manual (workflow_dispatch)
   └─ On push (to main/smoke_tests)

2. Runner Initialization
   ├─ Provision ubuntu-24.04-arm
   ├─ Checkout repository
   └─ Set metadata (timestamp, package slug)

3. Package Installation
   ├─ Parse install_commands JSON array
   ├─ Execute each command sequentially
   ├─ Capture stdout/stderr
   └─ Set install_status output

4. Version Detection
   ├─ Execute version_command
   ├─ Parse output (grep, awk, etc.)
   ├─ Set version output variable
   └─ Fallback to "unknown" on error

5. Test Execution
   ├─ Parse test_commands JSON array
   ├─ For each test:
   │  ├─ Record start time
   │  ├─ Execute test command
   │  ├─ Capture exit code
   │  ├─ Record end time
   │  ├─ Calculate duration
   │  └─ Set status (passed/failed)
   ├─ Aggregate results
   └─ Set overall status

6. Results Generation
   ├─ Create JSON (schema v1.0)
   ├─ Include all test details
   ├─ Add metadata (run URL, timestamp)
   └─ Write to test-results/<package>.json

7. Git Automation
   ├─ Configure git user (github-actions[bot])
   ├─ Stage JSON file
   ├─ Create commit with [skip ci]
   └─ Push with retry logic:
      ├─ Attempt 1: Direct push
      ├─ On fail: Pull --rebase
      ├─ On conflict: Auto-resolve (--ours)
      ├─ Retry up to 5 times
      └─ Exponential backoff (2s, 4s, 6s, 8s, 10s)

8. Workflow Completion
   ├─ Upload artifact (test results)
   ├─ Create GitHub Actions summary
   └─ Exit with status code
```

### Timing Breakdown

**Typical Execution (nginx example):**
```
00:00 - Start workflow
00:15 - Runner provisioned
00:30 - Repository checked out
00:45 - nginx installed (apt)
01:00 - Version detected
01:15 - Test 1: Binary check (1s)
01:16 - Test 2: Version output (1s)
01:17 - Test 3: Config syntax (2s)
01:19 - Test 4: Service start (5s)
01:24 - Test 5: HTTP response (3s)
01:27 - JSON generated
01:30 - Results committed
01:45 - Git push successful
02:00 - Workflow complete
```

**Total:** ~2 minutes

---

## Advanced Customization

### Custom Workflow Pattern

For complex testing scenarios, create a dedicated workflow:

**When to use:**
- Service management (systemd, supervisord)
- Network/HTTP testing
- Performance benchmarking
- Multi-step complex scenarios
- Database initialization
- Security scanning

**Example structure:**

```yaml
name: Test Complex Package on Arm64

jobs:
  test-package:
    runs-on: ubuntu-24.04-arm
    
    steps:
      # 1. Setup
      - name: Checkout
        uses: actions/checkout@v4
      
      # 2. Install with custom logic
      - name: Install package
        id: install
        run: |
          # Complex installation
          sudo apt-get update
          sudo apt-get install -y dependencies
          curl -L -o package.deb https://example.com/package.deb
          sudo dpkg -i package.deb
          sudo apt-get install -f
          
          echo "install_status=success" >> $GITHUB_OUTPUT
      
      # 3. Configure
      - name: Configure service
        run: |
          sudo tee /etc/package/config.yml <<EOF
          setting: value
          EOF
          sudo systemctl daemon-reload
      
      # 4. Individual test steps
      - name: Test 1 - Service starts
        id: test1
        run: |
          START=$(date +%s)
          sudo systemctl start package
          sleep 2
          systemctl is-active package
          END=$(date +%s)
          echo "duration=$((END - START))" >> $GITHUB_OUTPUT
          echo "status=passed" >> $GITHUB_OUTPUT
      
      - name: Test 2 - HTTP endpoint
        id: test2
        run: |
          START=$(date +%s)
          response=$(curl -s http://localhost:8080/health)
          [[ "$response" == *"ok"* ]]
          END=$(date +%s)
          echo "duration=$((END - START))" >> $GITHUB_OUTPUT
          echo "status=passed" >> $GITHUB_OUTPUT
      
      # 5. Generate results (manual JSON construction)
      - name: Generate results
        if: always()
        run: |
          cat > test-results/package.json <<EOF
          {
            "schema_version": "1.0",
            "package": {
              "name": "Package",
              "version": "$(package --version)"
            },
            "tests": {
              "passed": ${{ steps.test1.outcome == 'success' && steps.test2.outcome == 'success' && 2 || 0 }},
              "failed": ${{ steps.test1.outcome == 'failure' || steps.test2.outcome == 'failure' && 1 || 0 }}
            }
          }
          EOF
      
      # 6. Commit results
      - name: Commit results
        if: always()
        run: |
          # Use git automation pattern from existing workflows
          git config --global user.name 'github-actions[bot]'
          git add test-results/package.json
          git commit -m "Update package test results [skip ci]"
          
          for i in {1..5}; do
            if git pull --rebase origin ${{ github.ref_name }}; then
              if git push; then
                break
              fi
            else
              git checkout --ours test-results/package.json
              git add test-results/package.json
              git rebase --continue || true
            fi
            sleep $((i * 2))
          done
```

### Multi-Version Testing

Test multiple versions in parallel using matrix strategy:

```yaml
jobs:
  test-package:
    strategy:
      matrix:
        version: ['1.24', '1.25', '1.26']
        include:
          - version: '1.24'
            expected_features: 'http2'
          - version: '1.25'
            expected_features: 'http2,http3'
          - version: '1.26'
            expected_features: 'http2,http3,quic'
    
    runs-on: ubuntu-24.04-arm
    
    steps:
      - name: Install specific version
        run: |
          sudo apt-get install -y package=${{ matrix.version }}.*
      
      - name: Test version-specific features
        run: |
          for feature in $(echo ${{ matrix.expected_features }} | tr ',' ' '); do
            package --feature $feature
          done
```

### Conditional Testing

Skip certain tests based on conditions:

```yaml
- name: Test GPU functionality
  if: runner.arch == 'arm64' && env.GPU_AVAILABLE == 'true'
  run: |
    package --use-gpu test-file.dat
```

---

## Performance Optimization

### Caching Dependencies

Speed up workflows by caching package installations:

```yaml
- name: Cache APT packages
  uses: actions/cache@v4
  with:
    path: /var/cache/apt/archives
    key: apt-${{ runner.os }}-${{ hashFiles('**/packages.txt') }}
    restore-keys: apt-${{ runner.os }}-

- name: Install packages
  run: |
    sudo apt-get update
    sudo apt-get install -y package
```

### Parallel Test Execution

Run independent tests in parallel:

```yaml
jobs:
  test-unit:
    runs-on: ubuntu-24.04-arm
    steps:
      - name: Run unit tests
        run: package test --unit
  
  test-integration:
    runs-on: ubuntu-24.04-arm
    steps:
      - name: Run integration tests
        run: package test --integration
  
  test-performance:
    runs-on: ubuntu-24.04-arm
    steps:
      - name: Run performance tests
        run: package bench
```

### Timeout Management

Prevent hanging tests:

```yaml
- name: Test with timeout
  timeout-minutes: 5
  run: |
    package long-running-test
```

Or within commands:

```yaml
test_commands: |
  [
    {"name": "Test with timeout", "command": "timeout 30s package test"}
  ]
```

---

## Debugging

### Enable Debug Logging

Set secrets for verbose output:

```yaml
env:
  ACTIONS_RUNNER_DEBUG: true
  ACTIONS_STEP_DEBUG: true
```

### Capture Detailed Logs

```yaml
- name: Test package
  run: |
    set -x  # Enable command echoing
    package test 2>&1 | tee test-output.log
    
- name: Upload logs
  if: failure()
  uses: actions/upload-artifact@v4
  with:
    name: test-logs
    path: test-output.log
```

### Interactive Debugging

Use tmate for live debugging:

```yaml
- name: Setup tmate session
  if: failure()
  uses: mxschmitt/action-tmate@v3
  timeout-minutes: 15
```

### Common Debug Patterns

**Check environment:**
```yaml
- name: Debug environment
  run: |
    echo "=== System Info ==="
    uname -a
    cat /etc/os-release
    
    echo "=== Architecture ==="
    dpkg --print-architecture
    
    echo "=== Available packages ==="
    apt-cache policy package
    
    echo "=== Environment variables ==="
    env | sort
```

**Verbose test execution:**
```yaml
test_commands: |
  [
    {"name": "Debug binary", "command": "which -a package && file $(which package)"},
    {"name": "Debug version", "command": "package --version || package -v || package version"},
    {"name": "Debug libs", "command": "ldd $(which package)"}
  ]
```

---

## Complex Scenarios

### Database Testing

**PostgreSQL example:**

```yaml
install_commands: |
  [
    "sudo apt-get update",
    "sudo apt-get install -y postgresql",
    "sudo systemctl start postgresql"
  ]

test_commands: |
  [
    {"name": "Check service", "command": "systemctl is-active postgresql"},
    {"name": "Create database", "command": "sudo -u postgres createdb testdb"},
    {"name": "Run query", "command": "sudo -u postgres psql testdb -c 'SELECT version();'"},
    {"name": "Cleanup", "command": "sudo -u postgres dropdb testdb"}
  ]
```

### Container Testing

**Docker example:**

```yaml
install_commands: |
  [
    "sudo apt-get update",
    "sudo apt-get install -y docker.io",
    "sudo systemctl start docker",
    "sudo docker pull package:latest-arm64"
  ]

test_commands: |
  [
    {"name": "Check image", "command": "sudo docker images | grep package"},
    {"name": "Run container", "command": "sudo docker run --rm package:latest-arm64 --version"},
    {"name": "Test functionality", "command": "sudo docker run --rm package:latest-arm64 test-command"}
  ]
```

### Language-Specific Testing

**Python package:**

```yaml
install_commands: |
  [
    "python3 -m pip install --upgrade pip",
    "pip install package"
  ]

version_command: "python3 -c 'import package; print(package.__version__)'"

test_commands: |
  [
    {"name": "Import package", "command": "python3 -c 'import package'"},
    {"name": "Run tests", "command": "python3 -m pytest --version && pip install pytest && pytest"},
    {"name": "Check CLI", "command": "package-cli --help"}
  ]
```

**Node.js package:**

```yaml
install_commands: |
  [
    "curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -",
    "sudo apt-get install -y nodejs",
    "npm install -g package"
  ]

version_command: "package --version"

test_commands: |
  [
    {"name": "Check Node", "command": "node --version"},
    {"name": "Check npm", "command": "npm --version"},
    {"name": "Run package", "command": "package test-command"}
  ]
```

---

## Best Practices

### Test Design

**1. Start Simple, Add Complexity**
```yaml
# Phase 1: Basic
{"name": "Binary exists", "command": "command -v package"}

# Phase 2: Functionality
{"name": "Version works", "command": "package --version"}

# Phase 3: Real Usage
{"name": "Process file", "command": "package process test.dat"}

# Phase 4: Integration
{"name": "Full workflow", "command": "package init && package build && package deploy"}
```

**2. Idempotent Tests**
- Each test should clean up after itself
- Don't depend on test execution order
- Use unique temporary files/directories

**3. Fast Feedback**
- Put quick tests first
- Save long-running tests for later
- Use timeouts to prevent hanging

**4. Clear Failure Messages**
```yaml
{"name": "Check config", "command": "package validate config.yml || (echo 'Config validation failed' && cat config.yml && exit 1)"}
```

### Error Handling

**Graceful degradation:**

```yaml
version_command: "package --version 2>&1 | grep -oP '[0-9.]+' || package -v 2>&1 | grep -oP '[0-9.]+' || echo 'unknown'"
```

**Fail fast vs. Continue on error:**

```yaml
# Fail fast (default)
test_commands: |
  [
    {"name": "Critical test", "command": "must-pass-test"}
  ]

# Continue on error
test_commands: |
  [
    {"name": "Optional test", "command": "optional-test || true"}
  ]
```

### Maintenance

**Version pinning:**
```yaml
install_commands: |
  [
    "sudo apt-get install -y package=1.2.3-*"
  ]
```

**Automatic updates:**
```yaml
install_commands: |
  [
    "sudo apt-get install -y package"  # Always latest
  ]
```

**Documentation:**
- Add comments in workflow files
- Document expected behavior
- Note any quirks or workarounds

---

## Troubleshooting Guide

### Issue: Tests Pass Locally But Fail in CI

**Possible causes:**
1. Architecture difference (x86 vs ARM)
2. OS version difference
3. Missing dependencies
4. Different package versions

**Solutions:**
```yaml
# Test in ubuntu-24.04-arm container locally
docker run --rm -it --platform linux/arm64 ubuntu:24.04
apt-get update && apt-get install -y package
package test
```

### Issue: Flaky Tests

**Symptoms:** Tests pass sometimes, fail other times

**Common causes:**
- Race conditions
- Network timeouts
- Resource constraints

**Solutions:**
```yaml
# Add retries
test_commands: |
  [
    {"name": "Flaky test", "command": "for i in {1..3}; do package test && break || sleep 2; done"}
  ]

# Add delays
test_commands: |
  [
    {"name": "Wait for service", "command": "sleep 5 && curl localhost:8080"}
  ]
```

### Issue: Version Detection Fails

**Debug:**
```bash
# Run locally to see actual output
package --version
package -v
package version
```

**Common version detection patterns:**
```yaml
# Pattern: Clean version string
"package --version | grep -oP '[0-9.]+'"

# Pattern: Multiple fallback methods
"package --version 2>&1 | grep -oP 'v\K[0-9.]+' || package -v 2>&1 | awk '{print $2}'"

# Pattern: From file
"cat /usr/share/package/VERSION"
```

---

## Reference

### Exit Codes

- `0` - All tests passed
- `1` - At least one test failed
- `127` - Command not found
- `130` - Terminated by Ctrl+C
- `137` - Killed (OOM or timeout)

### Environment Variables

Available in workflows:
- `$GITHUB_WORKSPACE` - Checkout directory
- `$GITHUB_REF_NAME` - Branch name
- `$GITHUB_RUN_ID` - Workflow run ID
- `$GITHUB_REPOSITORY` - Repository name
- `$RUNNER_OS` - Operating system
- `$RUNNER_ARCH` - Architecture

### Workflow Syntax

**Conditionals:**
```yaml
if: success()           # Previous step succeeded
if: failure()           # Previous step failed
if: always()            # Run regardless
if: cancelled()         # Workflow cancelled
```

**Step outputs:**
```yaml
- id: step1
  run: echo "value=123" >> $GITHUB_OUTPUT

- run: echo ${{ steps.step1.outputs.value }}
```

**Matrix strategy:**
```yaml
strategy:
  matrix:
    version: [1, 2, 3]
    os: [ubuntu, debian]
  fail-fast: false
```

---

*Last Updated: November 17, 2025*  
*For basic usage, see [README.md](README.md)*  
*For complete guide, see [COMPLETE_GUIDE.md](COMPLETE_GUIDE.md)*
