# Bounded Smoke Repair

## Deployment Status

Repair is **disabled by default**. `SMOKE_REPAIR_ENABLED` must be exactly `true`
for request preparation and proposal admission. An unset flag does not disable
the ordinary weekly smoke run or its one confirmation retry. Merging this code
does not configure credentials, approve environments, enable repair, or prove a
live integration succeeded.

The model service runs separately from this public repository. This repository
does not receive model credentials, service access, private implementation,
private run identifiers, or private logs. Its callback accepts only fixed repair
operations and identities of already-public failure evidence. Detailed private
service configuration and security review belong with that service, not here.

Offline contract tests are not actual package execution or live model evidence.
Before activation, require both implementations reviewed, configuration verified,
a bounded end-to-end pilot, and any required organizational security review.
Human review and merge remain mandatory. No deadline or universal automatic fix
is guaranteed; unresolved failures remain unresolved.

## Triggers

- Friday night in US Central time: `0 3 * * 6` (Saturday 03:00 UTC).
- Manual main orchestrator dispatch.
- Smoke-scoped changes merged to `main`, classified using the complete Git diff.

Ordinary website, category, and generated-result-only changes retain their
normal build/deploy route without running the full smoke fleet. Repair approval
alone does not trigger orchestration: a smoke-scoped **merge** does.

One authenticated failed batch may receive one fresh same-SHA confirmation
dispatch with a unique nonce/run ID. Passing batches are not retried, original
failures remain recorded, and assertion failures are not relabelled transient.
Only the same registered package failing both runs is eligible for repair.
A failed original collector may also receive that single confirmation. A second
collector failure, missing evidence, timeouts, or unsupported layouts require
investigation rather than an invented package-failure context.

## Recovery Flow

```text
Full main run -> one confirmation of failures -> authenticated public request
  -> separate model service -> cumulative typed proposal callback
  -> independent public policy checks -> one immutable multi-package candidate
  -> all registered batches on hosted Arm -> candidate Global Summary
  -> failed candidate feedback -> revise and retest (at most three candidates)
  -> verified complete candidate success -> draft PR
  -> human review and merge -> fresh complete main run
```

The cycle controller is `smoke-repair-cycle.yml`, receiving only
`smoke-repair-cycle-proposal`. It groups the complete authenticated incident into
one candidate branch per iteration. Every iteration starts from the same reviewed
main commit and retains earlier fixes. The full-fleet verifier checks all registered
batches and packages, not just the repaired workflows, and confirms failed batches
once. Newly failing packages may enter the next proposal only after independently
verified persistent-failure evidence. Complete fleet success, exact artifacts and
required Arm probes must all agree before the draft publisher runs.

Candidate Global Summary is explicitly non-publishing. It cannot update dashboard
results or declare main recovered. Feedback is bound to the exact public controller
run, candidate SHA, artifact digest, cycle and preceding iteration. Incomplete
evidence is a blocker, not permission for another speculative model attempt. The
three-iteration limit is an escalation boundary, not a promise that all upstream
or infrastructure failures can be fixed automatically.

The following single-package protocol remains as a legacy compatibility path;
routine cycle automation uses the version 2 protocol below.

1. The preparation workflow authenticates current main, the original and
   confirmation runs, package registration, failed steps, and the evidence
   artifact. It uploads bounded `contexts.json` with sanitized public logs.
   Public source and logs are data, never executable instructions for a
   credential-bearing model job.
2. The separately reviewed service reads authenticated requests, enforces
   durable request/usage limits, and returns typed operations. Model prose,
   reasoning, errors, endpoints and private metadata are not public outputs.
3. `smoke-repair-receive.yml` accepts `repository_dispatch` of type
   `smoke-repair-proposal` from the configured App's exact login and numeric user
   ID. It binds the event to this public repository and current main, requires
   a completed failed original run's latest attempt no older than 72 hours,
   verifies artifact digest/producer timing, and independently rechecks both
   original and confirmation failures.
4. Trusted code compiles typed operations into edits of public source. Existing
   structural policy and shell syntax checks run before write credentials are
   minted and are repeated before publication. Arbitrary model-authored shell
   strings are not accepted.
5. The dedicated repair App stages an immutable candidate. A separate controller
   dispatches the actual package workflow at the final SHA on free public
   GitHub-hosted `ubuntu-24.04-arm`. Required probes and the original failure
   gate must pass. Exact run/attempt/job and hosted runner-group evidence are
   checked; runner labels alone are not proof.
6. Only after live native verification may the publisher open a draft PR. It
   rechecks ownership, head, title/body, native evidence and disabled auto-merge
   before reporting success. Passing a candidate does not verify the fleet.
7. Human review and merge start a new full smoke cycle. Recovery stays open
   until fresh full-run evidence verifies current main. Unsupported repairs,
   exhausted limits, missing approvals and failed validation require human
   follow-up, not fake success.

Callbacks are serialized without canceling an active publisher. Existing
incident branches or PR history cannot be reused or overwritten. GitHub queues
are bounded; a canceled or undelivered callback is not a successful repair.

## Public Callback

Cycle `client_payload` has exactly one field, `repair`, containing the document
below. This wrapper respects GitHub's ten-top-level-field dispatch limit; no
additional transport fields are permitted. The repair document has exactly
eleven fields: `schema_version` (integer 2),
`repository`, `base_sha`, `orchestrator_run_id`, `orchestrator_attempt`,
`context_artifact_id`, `cycle_id`, `iteration`, `previous_feedback_run_id`,
`previous_feedback_artifact_id`, and `proposals`. The cycle is the original run ID
and attempt separated by `-`. Iteration is 1 through 3. Both previous-evidence
pointers are null initially and required positive IDs thereafter. Proposals are
a unique sorted complete incident inventory, at most ten packages. Each contains
exactly `package_slug`, `context_sha256`, and `operations`; no raw source or private
metadata is accepted. An unchanged repeat proposal is rejected.

Legacy single-package `client_payload` has exactly nine fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `1`. |
| `repository` | Exact public dashboard repository. |
| `base_sha` | Full current main commit. |
| `orchestrator_run_id` | Original failed main run. |
| `orchestrator_attempt` | Exact latest failed attempt. |
| `context_artifact_id` | Exact authenticated preparation artifact. |
| `package_slug` | One registered failed package. |
| `context_sha256` | SHA-256 of the selected canonical public context. |
| `operations` | One through twelve fixed-vocabulary operations. |

Context canonicalization is UTF-8 JSON with sorted keys, separators `,` and `:`,
`ensure_ascii=False`, `allow_nan=False`, and no trailing newline. Duplicate JSON
keys and extra fields are rejected.

Operations use zero-based original step/line indexes:

- `prepend_apt` / `prepend_pip`: approved dependency names only; no arbitrary
  URLs, names, versions, indexes, flags or plugins.
- `prepend_parallelism`: an approved variable with a count from 1 through 4.
  Policy requires an unset control or a strictly reduced known value, with
  no ambiguous overrides.
- `curl_retry`: bounded integer retry parameters appended to an eligible
  existing setup download. The original URL and failure behavior stay intact.
- `github_release_download`: original step/line indexes and a source-bound
  research digest, never a model-provided URL. Independently fetched public
  release evidence must verify an Arm asset from the existing upstream repository,
  its downloaded bytes and SHA-256. Only recognized setup forms, same-minor stable
  patch upgrades and install-local version/checksum changes are supported. Global
  pins, unrelated sources, arbitrary hosts and test changes remain prohibited.

No free-form diagnosis, replacement source, shell command, private run URL or
reason may be sent. Unsupported proposals stay with the service for manual
investigation. The public policy remains authoritative even for schema-valid
operations. A reviewed skill is instruction data, not authority to expand these
limits, execute commands, change tests or bypass human review.

## Immutable Tests

Tests, assertions, final gates, step identities/order, permissions, runners,
action references, global baselines, outputs and reporting remain frozen. Setup
changes are limited to approved prerequisite/parallelism prefixes, bounded download
retries, and independently verified upstream release-download replacements.
Skipped required tests, removed packages, fabricated JSON,
source-only substitutes for runtime proof and suppressed failures cannot make
the system green.

Repair is not universal. The historical September 12 layout scan admitted 553
of 960 registered workflows and rejected 407 layouts. That is not current
coverage, a repair-success rate or evidence every failure is repairable.
Callable-only, credential-bearing and unsupported layouts remain manual.
No package workflow is rewritten merely to make it eligible.

## Candidate Provenance

Catalog-bound repair uses two immutable commits: a workflow-only source anchor,
then its child containing mechanical action-lock and catalog bindings. Only the
selected workflows, lock and catalog can differ from the reviewed base. The
compiler preserves identities/decisions and updates recognized advisory evidence
using the actual commit time and App attribution, not an earlier reviewer.
The full immutable base catalog is validated with checksum-pinned Hugo before
a delivery token is minted.

The bundle receipt binds both commits and every admitted package. Only the final candidate can supply native
success; subsequent edits invalidate it. Use a **merge commit**, not squash or
rebase, so the source anchor remains reachable in main. This prerequisite is
documented in the draft, not enforced by a per-PR GitHub setting; reviewers must
verify it. No branch protection is bypassed or merge setting silently changed.

## Public Configuration

| Variable | Purpose |
| --- | --- |
| `SMOKE_REPAIR_ENABLED` | Unset/false until an approved pilot. |
| `SMOKE_RECOVERY_MONITOR_ENABLED` | Separately enables the bounded recovery issue monitor. |
| `SMOKE_REPAIR_BRIDGE_BOT_LOGIN` | Exact authorized callback App login. |
| `SMOKE_REPAIR_BRIDGE_BOT_ID` | Bot account numeric user ID, not App ID. |
| `SMOKE_REPAIR_APP_BOT_LOGIN` | Dedicated candidate/draft publisher App login. |
| `DASHBOARD_DELIVERY_APP_BOT_LOGIN` | Existing generated-data identity; must differ from repair publisher. |
| `SMOKE_NOTIFICATION_LOGIN` | Human recovery owner. |

Only protected `smoke-repair-delivery` holds `SMOKE_REPAIR_APP_ID` and
`SMOKE_REPAIR_APP_PRIVATE_KEY`. Restrict it to reviewed main, preserve approved
protections, and install the App only on this repository. It needs Contents,
Pull requests and Workflows write, Actions read, and no organization permissions,
webhooks, or main/protection bypass.

Callback reception has only public read permissions. Native dispatch uses its
separate job-scoped Actions-write `GITHUB_TOKEN`. Candidate tests have no model
token, App identity or repair environment. Reporting uses a separate Issues-write
token. The model and candidate receive neither publication nor reporting tokens.

The request service's callback identity is separately configured. It must never
give this public repository access to private repositories. Its publication
permission and isolation are reviewed in the private configuration.

Required environment reviewers cause real approval pauses. This implementation
does not self-approve or remove those gates. Routine unattended draft creation
requires an explicitly approved environment policy, not merely an enable flag.
Human PR review/merge and production approval remain mandatory in either mode.

## Acceptance and Follow-up

Before routine activation, prove a real eligible failure through authenticated
request, private model call, exact callback, policy admission, complete candidate
fleet success, draft creation, human merge and a fresh complete main run. Exercise
wrong sender/SHA/context, replay, missing artifacts, malformed model output,
stale main, a new failure outside the original repair set, a second failed candidate,
failed native probes and exhausted budgets. None may yield a fake
pass or successful repair. Audit public logs/artifacts/PRs for private information.

Original failed runs stay failed. Each successful run verifies its own commit.
Merging one package fix can stale other drafts: do not automatically rebase
immutable branches or reuse old native evidence. Get fresh failure evidence on
the current commit. A manual rerun of an old workflow retains its old SHA.

Missing/stuck-run monitoring is best effort, not independent availability proof:
an outage can delay both smoke and monitor schedules. Keep a human owner and
manual dispatch path. New recovery incidents assign `SMOKE_NOTIFICATION_LOGIN`;
configure an eligible human assignee and keep GitHub notifications enabled.
Unsupported repairs and exhausted budgets remain open
for manual diagnosis. Do not manufacture failures or PRs to claim a pilot passed.

Generated results still require their existing review, merge and deployment.
Production promotion stays separate and is never authorized automatically by
repair. See [generated site data review](GENERATED_SITE_DATA_REVIEW.md).

Implementation: [request preparation](workflows/smoke-repair.yml),
[callback](workflows/smoke-repair-receive.yml), [compiler](scripts/smoke_repair_bridge.py),
[cycle controller](workflows/smoke-repair-cycle.yml),
[candidate fleet](scripts/smoke_repair_fleet.py),
[combined publisher](scripts/smoke_repair_bundle.py),
[policy](scripts/smoke_repair_policy.py), [native verifier](scripts/smoke_repair_native.py).
