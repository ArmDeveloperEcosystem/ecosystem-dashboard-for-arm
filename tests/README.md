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

## 🚀 Quick Start (15-20 Minutes)

### 1. **Understand the System**
- Tests run on native ARM64 GitHub runners (`ubuntu-24.04-arm`)
- Results stored as JSON badges in `data/test-results/`
- Badges auto-display on the Hugo dashboard

### 2. **Copy the Template**

Start with our template file:

```bash
cp .github/workflows/template-package-test.yml .github/workflows/test-redis.yml
```

### 3. **Customize for Your Package**

Edit `test-redis.yml` and replace placeholders:
- Change `<PACKAGE>` → `Redis` (display name)
- Change `<package>` → `redis` (lowercase, matches filename)
- Update install commands (apt, binary download, etc.)
- Update version detection command
- Add/modify test steps as needed

Example install section:
```yaml
- name: Install Redis
  run: |
    sudo apt-get update
    sudo apt-get install -y redis-server
```

### 4. **Add to Orchestrator**

Edit `.github/workflows/test-all-packages.yml` and add:

```yaml
test-redis:
  uses: ./.github/workflows/test-redis.yml
```

### 5. **Run and Verify**

```bash
# Test locally with act (optional)
act workflow_dispatch -j test-redis

# Or trigger via GitHub
gh workflow run test-redis.yml

# Check the results
cat data/test-results/redis.json
```

### 6. **See the Badge**

The badge will automatically appear on the Redis package page in the Hugo dashboard!

**💡 Tip:** Look at `test-nginx.yml` or `test-envoy.yml` for real working examples.

---

## 📊 System Overview

```
┌─────────────────────────────────────────────────────────┐
│  test-all-packages.yml (Orchestrator)                   │
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
│              │  │              │  │              │
│ 1. Install   │  │ 1. Install   │  │ 1. Install   │
│ 2. Version   │  │ 2. Version   │  │ 2. Version   │
│ 3. Test      │  │ 3. Test      │  │ 3. Test      │
│ 4. JSON      │  │ 4. JSON      │  │ 4. JSON      │
│ 5. Commit    │  │ 5. Commit    │  │ 5. Commit    │
└──────────────┘  └──────────────┘  └──────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│  data/test-results/*.json                               │
│  • JSON schema v1.0                                     │
│  • Auto-committed [skip ci]                             │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Hugo Dashboard Badge Display                           │
│  • Integrated in row-sub.html                           │
│  • Green/Red color coding                               │
└─────────────────────────────────────────────────────────┘
```

**Pattern:** All workflows follow the same structure - copy `template-package-test.yml` and customize.

---

## 🎯 Current Status

| Package | Tests | Status | Workflow |
|---------|-------|--------|----------|
| nginx | 5 | ✅ Passing | `test-nginx.yml` |
| Envoy | 4 | ✅ Passing | `test-envoy.yml` |

**Overall Test Pass Rate:** 100% (9/9 tests)

---

## 🔧 Key Files

## 🔧 Key Files

- **`.github/workflows/template-package-test.yml`** - Template for new package tests
- **`.github/workflows/test-nginx.yml`** - nginx example (5 tests)
- **`.github/workflows/test-envoy.yml`** - Envoy example (4 tests)
- **`.github/workflows/test-all-packages.yml`** - Orchestrator
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
1. Copy `template-package-test.yml` to `test-<package>.yml`
2. Customize install, version, and test steps
3. Add to `test-all-packages.yml`
4. Test locally before committing
5. Update this README's status table

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
