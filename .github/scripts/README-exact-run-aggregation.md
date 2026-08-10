# Exact-run aggregation foundation

This foundation defines the evidence contract for replacing timestamp-based batch
discovery with exact GitHub Actions run and artifact identities. It is deliberately
not connected to the production orchestrator, summary writer, deployment workflow,
or generated-data publisher.

## Trust boundary

The validator reads workflow blobs from the exact claimed Git commit, then uses
PyYAML's safe loader with aliases and duplicate keys disabled to discover the
reviewed batch topology. Ambient, ignored, or dirty workflow files cannot change
that immutable snapshot. It fails
unless batch numbers are contiguous, every package workflow is registered once,
every summary `needs` entry matches its package jobs, and every called package
workflow has exactly one `ubuntu-24.04-arm` job.

A canonical orchestration manifest must bind every batch to all of the following:

- repository, branch, full commit SHA, topology SHA-256, orchestration ID and
  creation timestamp;
- full workflow path and name, unique dispatch nonce, run ID and original attempt;
- `workflow_dispatch` event, exact head branch/SHA and terminal conclusion;
- every package registration's attempt-specific GitHub Jobs API ID, canonical name,
  URL, conclusion and execution window;
- artifact ID, name, size, SHA-256 digest, creation time and owning run ID.

Validation also requires the trusted parent job to provide the current orchestration
ID, the complete dispatch-nonce map, and a window no broader than 24 hours. Those
values are not trusted from the manifest itself, preventing a completed run from the
same commit from being replayed as a new orchestration.

The validator rejects missing, extra, duplicated, reordered, expired, stale,
cross-run, cross-commit and cross-dispatch evidence. A rerun attempt is not accepted;
an operational retry must create a fresh dispatch, nonce and run ID.

Every reachable external GitHub Action must use a full 40-character commit SHA.
Container actions, job containers and service containers must use a SHA-256 image
digest. The current legacy references are reported by topology discovery, but
manifest validation fails until they are pinned.
Local composite actions are resolved recursively from the same immutable commit;
missing metadata, cycles, nested reusable workflows, and mutable external references
inside a local action are rejected.

The downloaded archive bytes must match both the API-reported size and artifact
SHA-256 before the file tree is trusted. The ZIP central directory is bounded and
validated before Python creates member objects, and only those verified bytes are
extracted into a new private directory. Caller-supplied extracted trees are never
accepted as evidence.

The manifest is a trusted-parent document, not a batch artifact. Production must
construct it directly from authenticated GitHub workflow-run, attempt-specific Jobs,
and artifact API responses inside the isolated aggregation job. It must never accept
run, job, artifact or digest identities supplied by a batch workflow. Structural
validation cannot prove API custody on its own, so violating this boundary is an
activation blocker.

## Package truth model

Every package artifact must contain exactly one result for every batch registration
and one canonical `batch-attestation.json`. The sentinel records each result path and
SHA-256 digest. Symlinks, hard links, special files, unexpected directories, extra
files, oversized data, duplicate JSON keys, non-finite numbers and deeply nested JSON
are rejected.

Package results use six deterministic tests:

| Tests 1-5 | Test 6 | Result |
| --- | --- | --- |
| All pass | Pass | `6 passed`, successful run, passing badge |
| All pass | Fail | `5 passed / 1 failed`, failed run, `core_failed=0` |
| All pass | Approved defer | `5 passed / 1 skipped`, canonical `deferred` decision |
| All pass | Not applicable | `5 passed / 1 skipped`, canonical `not_applicable` decision |
| Any fail | `baseline_failed` skip | Failed run; `core_failed` equals baseline failures |
| Any baseline missing or skipped | Any | Contract rejection; no synthesized result |

An honest package failure is valid evidence and is retained as a failing package.
A provenance or schema failure invalidates the entire orchestration and produces no
aggregate attestation. The canonical aggregate derives `overall_status=failure` if
any retained package failed; otherwise it records `overall_status=success`.

## Resource limits

- at most 100 batch workflows;
- at most 100 legacy registrations per batch, with 45 recorded as the target limit;
- 2 MiB orchestration manifest and 256 KiB batch attestations;
- 2 MiB per package result;
- 128 MiB and 201 entries per extracted batch;
- 256 KiB central directory, 512-byte member names and no ZIP64 archives;
- 32 JSON levels and 100,000 JSON nodes.

The current 22-batch catalog contains 960 package workflows, with no batch above the
45-package target. This topology is reviewed independently from the still-dormant
exact-run publication path.

Topology discovery accepts exactly one collector contract in each batch during
the staged migration: either the current legacy collector or the strict
`collect-batch-observations` collector, never both. A strict batch must bind the
exact orchestration ID, dispatch nonce, batch number, and complete `needs`
payload, and its uploader must consume only the collector's declared artifact
path. Strict reusable and manual triggers must declare the two required
orchestration inputs as explicit strings and may not add another trigger.
Batches 1, 2, 7, 12, 13, and 17 must also retain their reviewed optional
`prefetch_run_id` and `prefetch_artifact_name` string inputs. Only the eight
reviewed package jobs may forward that pair: Spark and NiFi in batch 1, Pinot in
batch 2, Hive in batch 7, Hadoop and DolphinScheduler in batch 12, Storm in
batch 13, and Druid in batch 17. The strict contract rejects missing, altered,
partial, or additional forwarding and rejects prefetch inputs on every other
batch.

## Local validation

The canonical CI environment is Python 3.12 on Linux Arm64 with PyYAML 6.0.3. The
hash lock contains only that platform's wheel; it intentionally does not install on
macOS or x64. Local validation therefore requires an existing compatible PyYAML
6.0.3 environment, while Arm64 CI performs the checksum-pinned installation.

```bash
python3 .github/scripts/exact_run_aggregation.py topology --repository-root .
python3 .github/scripts/package_workflow_supply_chain.py \
  --expected-base-commit 73155d0d3a3dc73da08c62bc2bb7eccf281c6008
python3 -m unittest discover -s .github/scripts/tests -p 'test_*.py' -v
```

## Reviewed execution lock

`package_workflow_action_lock.json` binds the current 960 registered package
workflows and all 22 batch wrappers to an offline-reviewed dependency inventory.
The guarded migration pins 1,130 GitHub Action uses, pins the three job/service
containers to multi-architecture OCI index digests with confirmed Linux Arm64
manifests, disables persisted checkout credentials, and narrows workflow
permissions. The validator also binds the resulting workflow-set and exact-run
topology SHA-256 values, then proves that applying the transform again makes no
change. Action entries must carry internally consistent repository, ref, commit,
action-file, commit-verification, and independent `git ls-remote` evidence. Container
entries must preserve the exact registry/repository identity from the original tag;
changing both the repository and digest in the lock is rejected.

The lock is intentionally tied to dashboard commit
`73155d0d3a3dc73da08c62bc2bb7eccf281c6008`. Future package onboarding must
extend and review the lock rather than reusing mutable tags or silently changing
the dependency inventory. Pull-request CI passes the authenticated PR base SHA to
the validator. The initial migration requires that base to equal the reviewed source
commit so merely retaining an older Git object cannot satisfy guarded derivation.
On later relevant pull requests, an advanced base is accepted only when the exact
960-package and 22-batch byte snapshot still matches the reviewed hardened lock;
modified, missing, or malformed base evidence fails closed. The required check has
no manual-dispatch path: reruns remain bound to the pull request's authenticated base
SHA.

The foundation workflow intentionally uses an unfiltered `pull_request` trigger, so
GitHub creates the stable `Exact-run contract` job on every pull request. This makes
the job safe to configure as a required branch check: an unrelated pull request does
not leave branch protection waiting for a path-filtered workflow that never existed.
After the read-only checkout, a small scope step fetches and diffs the authenticated
`github.event.pull_request.base.sha`; it has no dispatch or caller-input fallback.
Changes to the action lock, online verifier, supply-chain and exact-run scripts,
tests, documentation or requirements, local actions, this foundation workflow, or
any `test-*.yml` workflow run the full contract. An unchanged relevant path set skips
the network, installation, validation, test, and lint steps, allowing the always-on
job to succeed quickly. Missing or malformed base identity, fetch failure, or diff
failure fails the job instead of silently classifying the pull request as unrelated.

When the lock or its live verifier changes, CI also queries the GitHub API and
independently runs `git ls-remote` to verify every recorded repository, commit,
action file, signature status, and mutable-ref resolution. Annotated tags require
the live Git tag object to name the reviewed tag and target the locked commit
directly; a nested or substituted tag object fails closed even when its final peel
reaches that commit. Unrelated pull requests retain the reviewed immutable snapshot
without failing merely because an upstream mutable ref later moves; adopting a newer
commit requires a fresh lock update and evidence review.

`validate-manifest`, `verify-batch`, and `aggregate` require trusted launch values
from the parent orchestration. Every nonce uses `BATCH=NONCE` syntax, must contain
64 lowercase hexadecimal characters, and every discovered batch must appear exactly
once; argument order is irrelevant. `--expected-not-before` and
`--expected-not-after` use RFC3339 timestamps and may span no more than 24 hours.
The aggregate command likewise requires every archive exactly once as
`--artifact-archive BATCH=PATH`:

```bash
python3 .github/scripts/exact_run_aggregation.py aggregate \
  --repository-root . \
  --manifest /trusted/manifest.json \
  --expected-repository ArmDeveloperEcosystem/ecosystem-dashboard-for-arm \
  --expected-branch main \
  --expected-sha <full-commit-sha> \
  --expected-orchestration-id orchestration-123-1 \
  --expected-not-before 2026-08-04T12:00:00Z \
  --expected-not-after 2026-08-04T13:00:00Z \
  --expected-dispatch-nonce 1=<64-hex-nonce> \
  --artifact-archive 1=/trusted/batch1.zip
```

Repeat both mapped arguments for every discovered batch.

## Activation sequence

1. Pin every reachable external action to a full commit SHA or container digest.
2. Rebalance legacy batches so every batch contains at most 45 packages.
3. Make every batch collector emit the strict result schema and attestation sentinel.
4. Add canonical run names plus orchestration-ID and dispatch-nonce inputs to each batch.
5. Dispatch batches with unique nonces and capture exact run IDs instead of timestamps.
6. Query the attempt-specific Jobs API and bind every package result URL and conclusion
   to its reviewed registration and exact job ID.
7. Build the manifest only in the trusted parent from authenticated GitHub API data.
8. Download the validated artifact by exact artifact ID and verify its size and digest.
9. Build one canonical aggregate by revalidating every archive; reject any invalid batch.
10. Send only the reviewed aggregate output to the isolated generated-data publisher.
11. Remove the old direct writer only after a bounded Arm64 run proves parity.

Until those steps are complete, the production result flow remains unchanged.

## Known cutover blockers

The current collector does not yet emit `batch-attestation.json` or every strict
regression metadata field. The 22 current batch workflows also lack the canonical
run name and trusted orchestration-ID/dispatch-nonce inputs. Some package
workflows use inconsistent Test 6 statuses for the same decision. Before activation,
separate migrations must wire the exact-run identities and normalize outputs to
`passed`, `failed`, `deferred`, or
`not_applicable`; generic `skipped` is reserved only for a baseline failure. Existing
failing decisions remain failures during that migration. This foundation
intentionally rejects incompatible evidence instead of silently converting it to a
green result.
