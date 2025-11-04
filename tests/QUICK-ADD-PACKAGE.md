# Quick Reference: Add New Package Test

## 1. Create Package Workflow

File: `.github/workflows/test-<package>.yml`

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
      package_name: "<Package Display Name>"
      package_slug: "<package>"
      package_category: "<Category>"
      package_language: "<language>"
      install_commands: |
        [
          "command1",
          "command2"
        ]
      version_command: "command-to-get-version"
      test_commands: |
        [
          {"name": "Test 1", "command": "test-command-1"},
          {"name": "Test 2", "command": "test-command-2"}
        ]
```

## 2. Add to Parent Workflow

File: `.github/workflows/test-all-packages.yml`

Add job:
```yaml
  test-<package>:
    uses: ./.github/workflows/test-<package>.yml
```

Update summary needs:
```yaml
  summary:
    needs: [test-nginx, test-envoy, test-<package>]
```

## 3. Commit and Push

```bash
git add .github/workflows/test-<package>.yml
git add .github/workflows/test-all-packages.yml
git commit -m "Add <package> functional tests"
git push
```

## 4. Trigger Test

- GitHub Actions → Test All Packages on ARM64 → Run workflow
- Or: GitHub Actions → Test <Package> on ARM64 → Run workflow

## Parameter Examples

### APT Package
```yaml
install_commands: |
  [
    "sudo apt-get update",
    "sudo apt-get install -y <package>"
  ]
version_command: "<package> --version | head -1"
```

### Binary Download
```yaml
install_commands: |
  [
    "wget https://releases.example.com/<package>-arm64 -O /tmp/<package>",
    "sudo mv /tmp/<package> /usr/local/bin/<package>",
    "sudo chmod +x /usr/local/bin/<package>"
  ]
```

### Python Package
```yaml
install_commands: |
  [
    "pip3 install <package>"
  ]
version_command: "python3 -c 'import <package>; print(<package>.__version__)'"
```

### Node Package
```yaml
install_commands: |
  [
    "npm install -g <package>"
  ]
version_command: "<package> --version"
```

## Test Command Patterns

### Check Binary Exists
```json
{"name": "Check binary", "command": "command -v <package>"}
```

### Check Version
```json
{"name": "Version check", "command": "<package> --version"}
```

### Import Test (Python)
```json
{"name": "Import test", "command": "python3 -c 'import <package>'"}
```

### Service Test
```json
{"name": "Start service", "command": "sudo systemctl start <service> && sudo systemctl is-active <service>"}
```

### HTTP Test
```json
{"name": "HTTP test", "command": "curl -s http://localhost:PORT | grep -q 'expected-text'"}
```

## Common Issues

| Issue | Solution |
|-------|----------|
| JSON syntax error | Validate JSON with `jq` |
| Command not found | Check ARM64 binary availability |
| Permission denied | Add `sudo` to command |
| Test timeout | Reduce test complexity or increase timeout |

## Checklist

- [ ] Created test-<package>.yml
- [ ] Added to test-all-packages.yml jobs
- [ ] Updated summary needs array
- [ ] Tested install commands locally (if possible)
- [ ] Validated JSON syntax
- [ ] Committed and pushed
- [ ] Triggered workflow
- [ ] Verified badge appears
