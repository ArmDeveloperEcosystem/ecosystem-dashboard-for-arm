# Apt Bootstrap Hardening

## Why We Added This

Recent Arm64 workflow failures in packages such as `prophet` and `dhcp` were not caused by package regressions. They failed because `apt-get update` hit transient Ubuntu mirror-sync issues on `ports.ubuntu.com`, which returned errors like:

- `File has unexpected size ... Mirror sync in progress?`
- exit code `100`

This creates false-red package failures in production:

- the package itself is fine
- the workflow goes red before package logic starts
- the global summary becomes noisy and less trustworthy

To reduce these false-reds, we introduced a shared local action:

- [apt-bootstrap/action.yml](/Users/ranman01/OneDrive%20-%20Arm/Documents/final-smoke-tests-main/.github/actions/apt-bootstrap/action.yml)

## What The Shared Action Does

The helper centralizes the common apt bootstrap pattern:

1. `apt-get clean`
2. remove stale apt lists
3. retry `apt-get update` up to a configured limit
4. exponential backoff between retries
5. install requested packages only after a successful update

This keeps transient mirror problems from turning healthy packages into false failures.

## Rollout Scope

### First rollout

The first rollout was intentionally limited to the workflows that recently failed in this way or are the clearest apt-native matches:

- [test-prophet.yml](/Users/ranman01/OneDrive%20-%20Arm/Documents/final-smoke-tests-main/.github/workflows/test-prophet.yml)
- [test-dhcp.yml](/Users/ranman01/OneDrive%20-%20Arm/Documents/final-smoke-tests-main/.github/workflows/test-dhcp.yml)
- [test-cassandra.yml](/Users/ranman01/OneDrive%20-%20Arm/Documents/final-smoke-tests-main/.github/workflows/test-cassandra.yml)
- [template-package-test.yml](/Users/ranman01/OneDrive%20-%20Arm/Documents/final-smoke-tests-main/tests/template-package-test.yml)

This first pass is deliberately narrow because not all workflows use apt the same way.

### Second rollout

After validating the helper and confirming the first false-red cases were true apt mirror flakes, we rolled the shared helper into the repo's largest exact-duplicate bootstrap pattern:

- `137` generated workflows that all used:
  - `sudo apt-get update >/dev/null`
  - `sudo apt-get install -y git curl jq tar unzip file ca-certificates >/dev/null`
  - optional `EXTRA_APT_PACKAGES`

That means the helper is now applied to:

- the first rollout workflows (`prophet`, `dhcp`, `cassandra`)
- plus the `137` exact-duplicate generated workflows
- plus the package workflow template for future additions

This is the largest safe centralization win because it removes a proven false-red failure class from the most repetitive apt bootstrap code without touching bespoke repo-add or multi-phase apt flows.

### Third rollout

After the exact-duplicate migration was stable, we completed the next broad safe codemod:

- exact single raw `apt-get update` + simple `apt-get install -y ...` pairs
- no repo-add logic
- no repeated update phases
- no docker-inner apt
- no special apt state management
- no package-list interpolation or shell control flow in the install line

This broadened the rollout to another:

- `447` workflows

## Current Coverage

After all completed rollout phases, the shared helper is now present in:

- `587` workflows

And the remaining repo-wide raw apt surface is down to:

- `197` workflows still using raw `apt-get update`
- `199` workflows still using raw `apt-get install`

Those remaining workflows are the bespoke/custom set and should be handled case by case rather than by bulk codemod.

## Why We Did Not Patch Everything At Once

Repo-wide audit found:

- `784` workflows contain raw `apt-get update` / `apt update`
- many are simple bootstrap cases
- many others are bespoke and should stay bespoke

Examples that should not be blindly codemodded first:

- workflows that add custom apt repositories
- workflows that run multiple `apt-get update` phases
- workflows that do apt inside containers
- workflows with special noninteractive or version-pinned package behavior

So the safe strategy is:

1. shared helper
2. patch obvious false-red apt cases first
3. expand to common duplicate patterns
4. leave bespoke apt flows custom

## Expected Production Benefit

This change should reduce false-red failures caused by transient Ubuntu mirror inconsistency on Arm64 runners, without changing the package test logic itself.

It improves:

- workflow reliability
- signal quality in batch runs
- truthfulness of failed-package reporting

It does **not** hide package failures. It only makes infrastructure bootstrap more resilient.

## Next Rollout Candidates

After the first rollout is proven, the next candidates are:

- other workflows using the exact same raw apt bootstrap snippet
- simple `apt-get update` + `apt-get install` workflows

Examples of packages worth hardening next if we keep seeing this failure class:

- `storm`
- `groovy_grails`
- other simple apt-native workflows hit by mirror sync flakes

## Remaining Bespoke Apt Cases

Even after the shared rollout, many workflows should still stay bespoke for now. These include:

- workflows that add custom apt repositories
- workflows with repeated `apt-get update` phases
- workflows with package-version pinning or special install flags
- workflows doing apt inside Docker/container contexts
- workflows where apt is only one part of a larger archive/bootstrap path

Those should be migrated only case by case, not by broad codemod.
