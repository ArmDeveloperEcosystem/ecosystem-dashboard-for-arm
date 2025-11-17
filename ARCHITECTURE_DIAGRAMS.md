# Testing Infrastructure Architecture

## System Overview Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     GitHub Actions (Arm64 Runners)              │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   test-      │  │   test-      │  │   test-      │         │
│  │   nginx.yml  │  │   envoy.yml  │  │   <pkg>.yml  │  ...    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
│         │                 │                 │                  │
│         └─────────────────┴─────────────────┘                  │
│                           │                                    │
│                  ┌────────▼────────┐                           │
│                  │  test-all-      │                           │
│                  │  packages.yml   │◄─── Scheduled (2 AM UTC) │
│                  └────────┬────────┘                           │
└───────────────────────────┼────────────────────────────────────┘
                            │
                            │ 1. Install package
                            │ 2. Run tests
                            │ 3. Generate JSON
                            │
                            ▼
            ┌───────────────────────────────┐
            │  data/test-results/           │
            │  ├── nginx.json               │
            │  ├── envoy.json               │
            │  └── <package>.json           │
            └───────────────┬───────────────┘
                            │
                            │ Git commit (auto)
                            │
                            ▼
            ┌───────────────────────────────┐
            │   Git Repository (main)       │
            └───────────────┬───────────────┘
                            │
                            │ Hugo build
                            │
                            ▼
            ┌───────────────────────────────┐
            │   Dashboard Website           │
            │                               │
            │  Package Card (expanded)      │
            │  ┌─────────────────────────┐  │
            │  │ Arm64 Tests             │  │
            │  │ ✅ 5 passing            │  │
            │  └─────────────────────────┘  │
            └───────────────────────────────┘
```

## Workflow Pattern Comparison

### Pattern 1: Custom Workflow (nginx)

```
.github/workflows/test-nginx.yml
    │
    ├─► Step 1: Install nginx (apt)
    │
    ├─► Step 2: Get version
    │
    ├─► Step 3-7: Run 5 custom tests
    │   ├─ Check binary exists
    │   ├─ Get version output
    │   ├─ Validate config syntax
    │   ├─ Start nginx service
    │   └─ Test HTTP response
    │
    ├─► Step 8: Generate JSON
    │
    └─► Step 9: Auto-commit results
```

**When to use**: Complex tests requiring service management, custom logic

---

### Pattern 2: Reusable Workflow (envoy)

```
.github/workflows/test-envoy.yml
    │
    │ Configuration (YAML):
    │ ├─ package_name: "Envoy"
    │ ├─ install_commands: [...]
    │ ├─ version_command: "..."
    │ └─ test_commands: [...]
    │
    └─► Calls: reusable-package-test.yml
            │
            ├─► Parse install_commands (JSON)
            ├─► Execute each command
            ├─► Parse version_command
            ├─► Parse test_commands (JSON)
            ├─► Run each test with timing
            ├─► Generate JSON results
            └─► Auto-commit results
```

**When to use**: Simple tests, rapid package addition (10 min each)

---

## Data Flow Detail

```
┌─────────────────────────────────────────────────────────────┐
│ 1. WORKFLOW EXECUTION (GitHub Actions)                      │
└───────────────────────────┬─────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │ Install Package│
                    └───────┬────────┘
                            │
                    ┌───────▼────────┐
                    │  Run Tests     │
                    │  - Test 1 ✅   │
                    │  - Test 2 ✅   │
                    │  - Test 3 ✅   │
                    └───────┬────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ 2. RESULTS GENERATION                                       │
│                                                             │
│  {                                                          │
│    "schema_version": "1.0",                                 │
│    "package": {                                             │
│      "name": "nginx",                                       │
│      "version": "1.24.0"                                    │
│    },                                                       │
│    "tests": {                                               │
│      "passed": 5,                                           │
│      "failed": 0,                                           │
│      "details": [...]                                       │
│    }                                                        │
│  }                                                          │
└───────────────────────────┬─────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │  Write JSON    │
                    │  to file       │
                    └───────┬────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ 3. GIT AUTOMATION                                           │
│                                                             │
│  git add data/test-results/nginx.json                      │
│  git commit -m "Update nginx test results [skip ci]"       │
│                                                             │
│  Retry loop (up to 5 times):                               │
│    ├─► git pull --rebase origin smoke_tests                │
│    │   └─► If conflict: git checkout --ours (auto-resolve) │
│    └─► git push                                             │
└───────────────────────────┬─────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │ Committed to   │
                    │ Repository     │
                    └───────┬────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ 4. HUGO BUILD (Static Site Generator)                      │
│                                                             │
│  Hugo reads: data/test-results/*.json                      │
│  Available as: $.metadata.Site.Data.test-results           │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ 5. TEMPLATE RENDERING                                      │
│                                                             │
│  File: row-sub.html (package expanded view)                │
│                                                             │
│  {{ with index $.metadata.Site.Data.test-results "nginx" }}│
│    <div class="field">Arm64 Tests</div>                    │
│    <div class="value">                                     │
│      <span style="color: green">                           │
│        {{ .tests.passed }} passing                         │
│      </span>                                               │
│    </div>                                                  │
│  {{ end }}                                                 │
└───────────────────────────┬─────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │  Dashboard     │
                    │  with Badge    │
                    └────────────────┘
```

## Scaling Example: Adding Redis

```
Step 1: Create workflow file (10 minutes)
┌─────────────────────────────────────────────────────────────┐
│ File: .github/workflows/test-redis.yml                     │
│                                                             │
│ name: Test Redis on Arm64                                  │
│ jobs:                                                       │
│   test-redis:                                               │
│     uses: ./.github/workflows/reusable-package-test.yml    │
│     with:                                                   │
│       package_name: "Redis"                                 │
│       package_slug: "redis"                                 │
│       install_commands: |                                   │
│         ["sudo apt-get install -y redis-server"]           │
│       version_command: "redis-server --version"            │
│       test_commands: |                                      │
│         [                                                   │
│           {"name": "Check binary", "command": "..."},      │
│           {"name": "Start service", "command": "..."}      │
│         ]                                                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
Step 2: Add to orchestrator (2 minutes)
┌─────────────────────────────────────────────────────────────┐
│ File: .github/workflows/test-all-packages.yml              │
│                                                             │
│ jobs:                                                       │
│   test-redis:                                               │
│     uses: ./.github/workflows/test-redis.yml               │
│                                                             │
│   summary:                                                  │
│     needs: [test-nginx, test-envoy, test-redis]            │
└─────────────────────────────────────────────────────────────┘
                            ↓
Step 3: Run workflow (automated)
┌─────────────────────────────────────────────────────────────┐
│ GitHub Actions → "Test Redis on Arm64" → Run workflow      │
│                                                             │
│ ✅ Installation successful                                  │
│ ✅ Version detected: 7.0.12                                │
│ ✅ 3 tests passed                                           │
│ ✅ Results committed: data/test-results/redis.json          │
└─────────────────────────────────────────────────────────────┘
                            ↓
Step 4: Badge appears (automatic)
┌─────────────────────────────────────────────────────────────┐
│ Dashboard → Redis package → Expanded view                  │
│                                                             │
│ Arm64 Tests: 3 passing ✅                                  │
└─────────────────────────────────────────────────────────────┘

Total time: ~12 minutes (mostly waiting for workflow to run)
```

## Concurrent Execution Example

```
┌────────────────────────────────────────────────────────────┐
│ Scenario: test-all-packages.yml runs (parallel execution) │
└────────────────────────────────────────────────────────────┘

Time: T+0 seconds
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  test-nginx  │  │  test-envoy  │  │  test-redis  │
│   (starts)   │  │   (starts)   │  │   (starts)   │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       │ Install nginx   │ Install envoy   │ Install redis
       │ Run 5 tests     │ Run 4 tests     │ Run 3 tests
       │                 │                 │
Time: T+180 seconds (nginx finishes first)
       │
       ├─► Generate nginx.json
       ├─► git commit "Update nginx test results"
       └─► git push ✅ (success - first to push)

Time: T+195 seconds (envoy finishes)
                     │
                     ├─► Generate envoy.json  
                     ├─► git commit "Update envoy test results"
                     ├─► git pull --rebase
                     │   └─ Fetch nginx.json update
                     └─► git push ✅ (success - rebased)

Time: T+210 seconds (redis finishes)
                                       │
                                       ├─► Generate redis.json
                                       ├─► git commit "Update redis..."
                                       ├─► git pull --rebase
                                       │   └─ CONFLICT in nginx.json?
                                       │      └─ Auto-resolve: --ours
                                       │      └─ git rebase --continue
                                       └─► git push ✅ (success - retry 1)

Result: All 3 workflows complete successfully in parallel
Total time: 210 seconds (vs 570 if sequential)
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Workflow Execution with Error Handling                     │
└─────────────────────────────────────────────────────────────┘

Install Package
    │
    ├─► Success ✅
    │   └─► Continue to tests
    │
    └─► Failure ❌
        └─► Log error
            └─► Set status = "failure"
                └─► Generate JSON with error details
                    └─► Continue to commit step

Run Tests
    │
    ├─► All pass ✅
    │   └─► status = "success", failed = 0
    │
    └─► Some fail ❌
        └─► status = "failure", failed = X
            └─► Generate JSON with failure details

Git Push
    │
    ├─► Push success ✅
    │   └─► Done
    │
    └─► Push failure ❌
        │
        └─► Retry Loop (5 attempts)
            │
            ├─► Attempt 1: pull --rebase
            │   ├─► Success → push ✅
            │   └─► Conflict → checkout --ours → continue
            │
            ├─► Attempt 2: (wait 2s) → retry...
            ├─► Attempt 3: (wait 4s) → retry...
            ├─► Attempt 4: (wait 6s) → retry...
            └─► Attempt 5: (wait 8s) → retry...
                │
                ├─► Success ✅ → Done
                └─► Final failure ❌ → Log error (non-fatal)

Hugo Build
    │
    ├─► Valid JSON ✅
    │   └─► Display badge
    │
    └─► Missing/Invalid JSON ⚠️
        └─► Gracefully skip badge (no error)
```

## Summary Stats

```
┌──────────────────────────────────────────────────────┐
│ Infrastructure Metrics                               │
├──────────────────────────────────────────────────────┤
│ Workflows Created:              4                    │
│ Documentation Files:            8                    │
│ Lines of Code:                  ~1,500               │
│ Test Coverage (packages):       2                    │
│ Test Coverage (tests):          9                    │
│ Pass Rate:                      100%                 │
│ Time to Add Package:            ~10 min              │
│ Avg Test Duration:              3 min                │
│ Concurrent Execution:           Yes (parallel)       │
│ Auto-Conflict Resolution:       Yes (--ours)         │
│ Retry Attempts:                 5                    │
│ Daily Scheduled Runs:           2 AM UTC             │
│ Breaking Changes:               0                    │
└──────────────────────────────────────────────────────┘
```
