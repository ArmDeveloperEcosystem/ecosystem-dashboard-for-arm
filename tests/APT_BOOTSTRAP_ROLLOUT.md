# Apt Bootstrap Hardening

Current as of 2026-05-14.

## Why This Exists

Some Arm64 workflow failures were not package regressions. They happened before package logic started because `apt-get update` hit transient Ubuntu mirror-sync errors on `ports.ubuntu.com`, such as:

```text
File has unexpected size ... Mirror sync in progress?
```

Those failures create false-red package results. The package may be healthy, but the workflow goes red before the actual smoke test begins.

## Shared Helper

The shared helper lives at:

```text
.github/actions/apt-bootstrap/
```

It provides two supported usage styles:

```yaml
- uses: ./.github/actions/apt-bootstrap
  with:
    packages: git curl jq
```

or:

```bash
bash .github/actions/apt-bootstrap/bootstrap.sh --packages "git curl jq"
```

## What The Helper Does

The helper centralizes the safe apt bootstrap pattern:

1. cleans stale apt metadata
2. retries `apt-get update`
3. backs off between retries
4. installs requested packages only after update succeeds
5. keeps package workflow logic focused on the actual smoke test

## Current Coverage

Current repository scan:

| Item | Count |
|---|---:|
| Workflow files mentioning `apt-bootstrap` | 596 |
| Direct composite action uses | 133 |
| Remaining raw `apt-get update` references | 225 |
| Remaining raw `apt-get install` references | 261 |

The remaining raw apt usage is not automatically wrong. Many of those workflows are bespoke and should be reviewed case by case, especially when they:

- add custom apt repositories
- install inside containers
- use multi-phase apt state
- pin specific package versions
- intentionally combine apt with external setup tooling

## Why We Did Not Bulk-Patch Everything

Bulk replacing every apt command would be risky. Some workflows need custom repository setup or package order. The helper is safest for common bootstrap cases and known mirror-flake false-reds.

The rule is:

- use `apt-bootstrap` for simple runner bootstrap installs
- keep bespoke apt logic where package setup genuinely needs it
- migrate additional workflows only after checking the workflow-specific install path

## Production Benefit

The helper reduces false-reds caused by transient apt mirror issues on Arm64 runners. That improves:

- batch reliability
- global summary signal quality
- confidence that red means package/test failure, not infrastructure flake

## Maintainer Checklist

When editing a package workflow:

1. If it only needs common apt packages, prefer `apt-bootstrap`.
2. If it has custom apt repositories or container-inner apt, leave it custom unless tested.
3. If a workflow fails during `apt-get update`, first determine whether it is an apt mirror flake or a real package issue.
4. Do not change package validation logic just to hide an infrastructure failure.
