# Package Testing Infrastructure

Welcome to the Arm Ecosystem Dashboard package testing system! This directory contains all documentation and resources for our automated functional testing infrastructure.

## 📚 Documentation Guide

We've organized our documentation to help you find what you need quickly:

### **[COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md)** - Your Main Resource
**Start here!** This is your comprehensive, all-in-one guide covering:
- System overview and architecture
- Quick start guide (5 minutes to first test)
- Step-by-step package addition instructions
- Test results JSON schema reference
- Troubleshooting and debugging
- Deployment workflows

### **[PIPELINE_REFERENCE.md](./PIPELINE_REFERENCE.md)** - Advanced Topics
For advanced users and maintainers:
- Detailed pipeline execution flow
- Advanced customization options
- Performance optimization techniques
- Complex debugging scenarios
- Edge cases and special configurations

---

## 🚀 Quick Start (5 Minutes)

### 1. **Understand the System**
- Tests run on native ARM64 GitHub runners (`ubuntu-24.04-arm`)
- Results stored as JSON badges in `data/test-results/`
- Badges auto-display on the Hugo dashboard

### 2. **Add Your First Package**

Create `.github/workflows/test-your-package.yml`:

```yaml
name: Test Your Package on Arm64

on:
  workflow_dispatch:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM UTC

jobs:
  test-your-package:
    uses: ./.github/workflows/reusable-package-test.yml
    with:
      package_name: "your-package"
      package_display_name: "Your Package"
      package_version: "1.2.3"
      install_commands: |
        sudo apt-get update
        sudo apt-get install -y your-package
      version_command: "your-package --version"
      test_commands: |
        [
          {
            "name": "Binary Check",
            "command": "which your-package"
          },
          {
            "name": "Version Check",
            "command": "your-package --version"
          },
          {
            "name": "Functional Test",
            "command": "your-package --test"
          }
        ]
```

### 3. **Run and Verify**
```bash
# Trigger the workflow
gh workflow run test-your-package.yml

# Check the results
cat data/test-results/your-package.json
```

### 4. **See the Badge**
The badge will automatically appear on your package page in the Hugo dashboard!

---

## 📊 System Overview

```
┌─────────────────────────────────────────────────────────┐
│  test-all-packages.yml (Parent Orchestrator)            │
│  • Triggers all package tests in parallel               │
│  • Runs daily at 2 AM UTC                               │
│  • Aggregates results                                   │
└─────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ test-nginx   │  │ test-envoy   │  │ test-redis   │
│   .yml       │  │   .yml       │  │   .yml       │
└──────────────┘  └──────────────┘  └──────────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
        ┌─────────────────────────────────────────┐
        │  reusable-package-test.yml              │
        │  • Generic test template                │
        │  • Install → Version → Test → Badge    │
        │  • Auto-conflict resolution             │
        └─────────────────────────────────────────┘
                           │
                           ▼
        ┌─────────────────────────────────────────┐
        │  data/test-results/package.json         │
        │  • JSON schema v1.0                     │
        │  • Auto-committed [skip ci]             │
        └─────────────────────────────────────────┘
                           │
                           ▼
        ┌─────────────────────────────────────────┐
        │  Hugo Dashboard Badge Display           │
        │  • Integrated in row-sub.html           │
        │  • Green/Red color coding               │
        └─────────────────────────────────────────┘
```

---

## 🎯 Current Status

| Package | Tests | Status | Workflow |
|---------|-------|--------|----------|
| nginx | 5 | ✅ Passing | `test-nginx.yml` |
| Envoy | 4 | ✅ Passing | `test-envoy.yml` |

**Overall Test Pass Rate:** 100% (9/9 tests)

---

## 🔧 Key Files

- **`.github/workflows/reusable-package-test.yml`** - The reusable workflow template
- **`.github/workflows/test-all-packages.yml`** - Parent orchestrator
- **`data/test-results/*.json`** - Test result JSON files
- **`themes/.../row-sub.html`** - Badge display template

---

## 📖 Learn More

- **New to the system?** → Read [COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md) from start to finish
- **Need to add a package?** → Jump to the "Adding New Packages" section in [COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md)
- **Debugging an issue?** → Check the "Troubleshooting" section in [COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md)
- **Want to customize workflows?** → See [PIPELINE_REFERENCE.md](./PIPELINE_REFERENCE.md)

---

## 🤝 Contributing

When adding new packages:
1. Follow the pattern in `test-nginx.yml` or `test-envoy.yml`
2. Use the reusable workflow template for consistency
3. Test locally before committing
4. Update this README's status table

---

## 📝 Schema Reference (Quick)

Test results JSON structure:
```json
{
  "schema_version": "1.0",
  "package_name": "nginx",
  "status": "passing",
  "tests_passed": 5,
  "tests_failed": 0,
  "last_updated": "2024-01-15T10:30:00Z"
}
```

For complete schema documentation, see [COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md#test-results-json-schema).

---

**Questions?** Check [COMPLETE_GUIDE.md](./COMPLETE_GUIDE.md) or [PIPELINE_REFERENCE.md](./PIPELINE_REFERENCE.md) for detailed answers!
