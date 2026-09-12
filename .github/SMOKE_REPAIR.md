# Bounded Smoke Repair

## Status

The repository implements a bounded repair path, but it is **disabled by
default**. Repair jobs require repository variable `SMOKE_REPAIR_ENABLED` to be
exactly `true`; unset or `false` leaves them disabled. This switch does not
disable ordinary smoke validation or its confirmation retry. **Merging alone
does not activate repair.** Keep repair disabled throughout implementation.

Repository variables, protected environments, the dedicated GitHub App, and
live end-to-end integration have **not been configured or verified in this
change**. No live model call, hosted repair validation, repair PR, or successful
full-main cycle is claimed by this documentation. Offline tests are not live
integration evidence. The rollout order remains: **the user tests, Chris
reviews, then a human merges** after required checks and approvals.

**The Arm proxy adapter is ready for offline use only; live integration is
blocked.** `Arm-Debug/devops-actions` is `internal`, while the dashboard is
public. GitHub does not permit internal actions to be shared with public
repositories; see [the official sharing rules](https://docs.github.com/en/enterprise-cloud@latest/actions/how-tos/reuse-automations/share-with-your-enterprise).
Runner authorization and action allowlisting cannot override that restriction.
A supported token-delivery path requires an explicit decision and review before
activation, as described in the rollout below.

The `propose` job retains `ubuntu-24.04-arm`. Its model request was replaced by
`Require approved Arm model authentication`, which prints a fixed diagnostic
and exits with status 1; the static model-secret binding was removed. Even with
`SMOKE_REPAIR_ENABLED=true`, this workflow cannot mint a model token, call the
model, stage a candidate, or open a repair draft.

This is not a universal fixer. It never automatically approves, merges, or
deploys, and cannot turn an original failure into a passing result.

## Layout-Admission Coverage

The registered-topology scan reported for this change examined **960 registered
packages**. Of these, **553 passed both policy and native contract layout
derivation**, and **407 had unsupported layouts**. This is a coverage snapshot
of layout admission only, **not validated repair counts**, successful native
runs, or evidence that 553 packages or their failure causes can be fixed.

The reported unsupported-layout breakdown is:

| Admission rejection | Packages |
| --- | ---: |
| No `workflow_dispatch` | 374 |
| Explicit secrets or tokens | 20 |
| Unsupported failure gate | 4 |
| Timeout greater than 60 minutes | 1 |
| Conditional job | 1 |
| Unnamed steps | 7 |
| Total unsupported | 407 |

Callable-only workflows (`workflow_call` without `workflow_dispatch`) and
delegated layouts outside the standalone native contract require manual
handling. A supported layout is only a prerequisite: a real failure must still
have authenticated evidence, a repair within the three allowed classes, policy
admission, exact hosted Arm validation, and human review. Causes outside the
bounded policy remain manual even for one of the 553 admitted layouts.

**No package workflows were changed to force eligibility.** The scan does not
authorize adding dispatch triggers, removing credential references, weakening
gates, or otherwise rewriting a package layout to fit the repair system. There
is no full-catalog automatic-fix claim; workflow or contract changes can also
change this snapshot's counts.

## Triggers and Confirmation

[The main orchestrator](workflows/test-all-packages-orchestrator.yml) starts the
full 22-batch smoke cycle through:

- Weekly schedule `0 3 * * 6`: Saturday 03:00 UTC, which is Friday 10 PM CDT or
  9 PM CST in US Central time.
- Manual `workflow_dispatch` on `main`.
- Pushes to `main`, including merged PRs, whose authenticated full diff selects
  smoke code or its execution dependencies. Mixed changes include smoke scope;
  ordinary website-only changes and generated test-result data do not.

Before repair, an authenticated, completed failed batch with a complete exact
job inventory and a successful collector may receive **one confirmation
retry**. This is a fresh same-SHA dispatch with a new nonce and run ID, still
attempt 1, not a rerun that overwrites the original identity. Successful batches
are not rerun. Original failures and confirmation evidence are retained.
Assertion failures are not relabelled as transient; the curl diagnostic is not
permission to ignore a failure.

The optional repair path runs only after the main orchestration fails and its
exact evidence artifact is available. It independently authenticates the
original and failed confirmation runs; not every orchestration failure is an
eligible package repair. The repair workflows are reusable `workflow_call`
workflows, not additional weekly schedules or standalone manual entry points.
The same registered package must fail in both runs. A package that first fails
during the batch confirmation has not confirmed its own failure and is reported
for manual investigation, not automatically repaired in that incident.

## Repair Flow

```text
Authenticated persistent failure -> data-only model -> policy admission
-> immutable candidate branch -> real hosted Arm run -> verified draft PR
-> human review and merge -> a new full main smoke cycle
```

1. **Authenticate evidence.** The preparation job verifies the public repository,
   current `main` SHA, orchestration/run/attempt identities, exact artifact, both
   failed batch runs, package registration, and failed steps. It reads source
   from the authenticated base and prepares a bounded, sanitized public log
   excerpt. Both failures require completed, uniquely identified failing steps;
   contradictory or extra confirmation history is rejected. Missing, ambiguous,
   or stale evidence fails closed.
2. **Request data only.** A separate analysis job projects the authenticated
   context onto the model's allowlisted fields and includes the validator's full
   policy description and approved dependency names as validation feedback. It requests
   one bounded OpenAI Responses proposal per package: `diagnosis`, `edits`, and
   `unresolved_reason`. Source and logs are untrusted data. The model has no
   tools, shell, web access, or authority to execute its output. Requests use
   `store: false`; malformed, refused, incomplete, or oversized output fails
   closed. There is no model retry loop or fallback model.
3. **Admit the patch.** Trusted code independently checks the exact edit anchors,
   supported workflow layout, narrow repair classes, frozen test/gate behavior,
   and shell syntax. Syntax checking is not execution or proof of repair. This
   check runs before a delivery token is minted and is repeated later.
4. **Stage an immutable candidate.** The dedicated repair App creates one new
   `automation/smoke-repair/<run-id>-<attempt>-<package-slug>` branch at a bound
   candidate SHA. Existing incident branches or PR history are not overwritten.
   The allowed diff is the admitted package workflow plus the trusted mechanical
   reseal of its action-lock data; the model cannot change action pins or choose
   lock edits. The publisher does not check out or run candidate code.
5. **Validate on real hosted Arm.** A separate controller dispatches the actual
   package workflow on the candidate branch using `ubuntu-24.04-arm`. It binds
   the run and attempt to the exact candidate, verifies the native job identity
   and runner evidence, and requires the original mandatory tests and final
   failure gate to complete successfully. Static checks, mock results, model
   claims, or a receipt alone cannot replace this live evidence.
   All source workflow steps must be present with their exact names and numbers.
   Requested runner labels alone are insufficient: the job must belong to the
   standard GitHub-hosted runner group, and the repository must remain public.
6. **Open only a verified draft.** Publication rechecks policy, the unchanged
   base and candidate identities, and live native evidence. Only then may the
   dedicated App open the exact draft PR with links to the original failure,
   confirmation failure, and native run. Unresolved or unsuccessful stages
   produce a manual-investigation report, not a placeholder PR or a fake pass.
   After final native verification, the publisher rereads the draft's ownership,
   commit, title, body, and disabled auto-merge state before reporting success.
7. **Require human review and a new main cycle.** The user tests and examines
   the evidence; Chris reviews before a human merges with required checks and
   approvals. That smoke-code merge triggers a new full cycle on the new
   `main`, including all batches and Global Summary. Candidate-only success
   does not verify the whole fleet, retroactively clear the original failure,
   publish generated results, or authorize deployment.

## Repository Repair Skill

[The smoke-repair skill](skills/smoke-repair/SKILL.md) is reviewed instruction
data for the existing tool-free model adapter, not a separately installed agent.
It covers evidence-based diagnosis, the three repair classes, immutable tests,
stop conditions, exact proposal output, and the boundary between a suggestion
and independently verified recovery.

`propose()` loads the complete file from the adapter's fixed repository-relative
location on each request; environment variables, working directories, model
evidence, and CLI arguments cannot select another skill. Missing, invalid,
oversized, symlinked, or non-regular skill files fail before model transport.
The request builder remains pure and takes the trusted skill text explicitly.
The caller must supply an immutable, authenticated base checkout for both the
adapter and skill, separate from artifacts and candidate execution. Anchoring
the path is not itself proof of checkout provenance.

The fixed developer guard and independent policy remain authoritative. The
adapter generates output limits from its constants; policy feedback supplies
approved dependency names and script limits. Neither the skill nor model output
can change those enforced limits or authorize execution. Skill-only changes
enter smoke routing and the foundation CI scope. Tests cover loading, request
isolation, and reference repair cases; offline evaluation is not evidence of
Arm-proxy model behavior or a live repair. The authentication block described
above is unchanged, and adding this skill does not enable repair.

## Allowed Repairs and Limits

Only these classes can be admitted within a supported package workflow:

- Approved build-prerequisite additions using the policy's literal installation
  forms and package allowlists. Existing packages and installation options must
  remain intact; arbitrary packages, new test plugins, scripts, or URLs are not
  approved additions.
- Bounded build-parallelism exports such as `MAKEFLAGS` or
  `CMAKE_BUILD_PARALLEL_LEVEL`, using counts 1-4. Existing approved values may
  only be reduced; original build and test commands remain verbatim.
- The exact bounded retry suffix on an eligible existing setup curl download:
  `--retry N --retry-delay D --retry-max-time T`, with `N=1..5`, `D=1..10`, and
  `T` one of `30`, `60`, `90`, or `120`. The original HTTPS command and its
  failure behavior remain intact. Exactly one credential-free HTTPS URL and
  supported download options are required; uploads, config files, multiple
  transfers, and ambiguous or overridden failure flags require manual handling.

In-place setup edits after multiline quotes, heredocs, command continuations,
or other unsupported shell context require manual review. Command-looking text
inside shell data is not an editable command. A permitted prefix before the
entire unchanged original script remains a separate supported operation.

The original test scripts, assertions, output writes/checks, and final gates are
immutable. Approved prerequisites or parallelism may be prefixed before an
entire original test script, never inserted to bypass its checks or success
outputs. No new skips, weakened security checks, changed baselines, substituted
source-only proof, or failure masking are allowed. Workflow structure, step
IDs/names/order, permissions, triggers, action references, and reporting/version
steps are frozen. Unsupported layouts, action-backed probe changes, URL
relocations, and repairs outside these classes require manual investigation.

The cap is **10 packages per incident**, with **at most two parallel package
repairs** and **one model proposal per package**. More than 10 eligible failures
stops the automatic handoff for manual triage; it does not silently pick a
subset. Each proposal has at most 12 edits, plus adapter payload and timeout
limits. The policy separately bounds prerequisite additions within each script.
The model request is bounded to 8192 output tokens and a 60-second deadline.
Native polling defaults to 90-second intervals within a 60-minute deadline, to
leave API capacity for two workers and their final identity checks. Other
repository workflows share GitHub's API limits. Controllers recheck the free
rate-limit endpoint at most every ten primary requests, retain a reserve for
concurrent workers and reporting, and wait for an authenticated reset only
when it fits the remaining deadline. Both refs are rechecked after a wait
before dispatch, and a POST is never repeated. The empty prior-run inventory,
public repository check, ref checks, and dispatch reserve their quota together,
so a quota wait cannot separate the inventory check from dispatch. Publication's
repeated native checks and publication checkpoints share one 180-second deadline.
Unavailable quota or malformed rate
evidence stops verification without authorizing a PR.

GitHub reads and writes are not atomic. An in-flight API call can outlast a
checkpoint deadline, or concurrent changes can invalidate an already-created
draft. Such cases report failure, not verified publication; a human may need to
inspect the retained branch or draft. No automatic deletion or merging occurs.

Structural admission and native success do not prove semantic equivalence or
complete coverage. Dependency additions execute upstream code, and an unchanged
probe can still be insufficient or wrong. Human review remains mandatory.

## Arm Proxy Adapter

The adapter uses fixed HTTPS host `openai-api-proxy.geo.arm.com`, port 443, and
path `/api/providers/openai/v1/responses`. There is no arbitrary base URL or
`OPENAI_BASE_URL` override, redirect, retry, ambient proxy discovery, or fallback
endpoint/model. Verified TLS with system CA trust, bounded reads, the 60-second
deadline, content-free errors, and avoidance of `SSLKEYLOGFILE` remain required.

`SMOKE_REPAIR_OPENAI_API_KEY` remains the adapter input for a short-lived Arm
token, not a static-secret fallback. It accepts 1-8192 visible ASCII characters
(`0x21`-`0x7e`), with no whitespace/control characters. Test bounds with synthetic
credentials only; issued-token format, lifetime, authorization, and model
compatibility have not been live-tested. Invalid or rejected tokens fail closed.

Infrastructure prerequisites are runner authorization; an action shareable with
its caller and allowlisted at its reviewed pin; SPIFFE/AWS identity and system
setup; network access and system CA trust; and an authorized token/model that
supports the exact strict Responses schema. The dedicated repair App, protected
environments, and approved live pilot remain separate prerequisites.

Identity setup can leave credentials on the runner; step-scoped environment
variables are not an execution sandbox. Use only trusted base tooling on the
approved ephemeral runner, never package/candidate code. Do not log or transfer
tokens, put them in artifacts or job outputs, copy registration secrets to
arbitrary machines, or disable TLS verification. Other repair jobs and candidate
tests retain free hosted Arm `ubuntu-24.04-arm` and unchanged native evidence
requirements. This adapter change does not authorize a runner switch.

## Configuration and Credentials

Configure only after the integration decision and the user test and Chris
review stages authorize rollout.
The required repository variables are:

| Variable | Required value or purpose |
| --- | --- |
| `SMOKE_REPAIR_ENABLED` | Unset or `false` by default; exactly `true` only for an approved activation. |
| `SMOKE_REPAIR_MODEL` | Explicit model supporting the adapter's strict Responses JSON schema; no hardcoded default or fallback. |
| `SMOKE_REPAIR_APP_BOT_LOGIN` | Exact dedicated repair App login ending in `[bot]`, matching the installed App. |

The approved model must support the exact strict schema, including `maxLength`
and `maxItems`, not merely JSON output. The [official OpenAI documentation](https://developers.openai.com/api/docs/guides/structured-outputs)
describes model-specific restrictions. Compatibility still requires the live pilot;
offline adapter tests do not establish account access or model support.

Keep the existing `DASHBOARD_DELIVERY_APP_BOT_LOGIN` configured: the publisher
requires it to verify that the repair App is a **different** identity from the
generated-data App. `SMOKE_REPAIR_APP_SLUG` is derived from the token-mint action,
not a new operator-supplied setting. Optional `SMOKE_NOTIFICATION_LOGIN` selects
the notification recipient; otherwise workflows use `github.actor`.

Use two separate environments restricted to jobs from protected, reviewed `main`,
with the dedicated least-privilege identities described here. The organization
must explicitly approve their protection policy.

For an initial pilot, the organization may require independent environment
reviewers, self-review prevention, and no administrator bypass. If required
reviewers are retained, analysis and delivery jobs pause for approval on each
incident; delivery includes both staging and draft publication. That mode is
**approval-gated, not fully unattended**.

Routine unattended operation through draft PR creation requires an
organization-approved environment policy that permits those jobs to run
automatically on protected `main`, while preserving branch restrictions,
credential separation, and the dedicated least-privilege App. This is an
organization policy choice, not authority for automation to approve or bypass
environment gates. No environment protections are configured, changed, or
removed in this change. **Human PR review and human merge remain mandatory in
either mode**; generated-data and production approval policies are unchanged.

Repair App credentials must remain delivery-environment secrets, not broadly
available repository or organization secrets. The model token source is pending:

| Environment | Credential source | Consumer |
| --- | --- | --- |
| `smoke-repair-analysis` | Pending approved short-lived token source; adapter input `SMOKE_REPAIR_OPENAI_API_KEY` | Proposal step blocked by guard; no static secret fallback. |
| `smoke-repair-delivery` | Environment secret `SMOKE_REPAIR_APP_ID` | Dedicated repair GitHub App token minting. |
| `smoke-repair-delivery` | Environment secret `SMOKE_REPAIR_APP_PRIVATE_KEY` | Private key for that same dedicated App. |

Install the **dedicated repair App only on this repository**. Its repository
permissions are Contents read/write, Pull requests read/write, Workflows
read/write, Actions read-only, and implicit Metadata read. Grant no organization
permissions and configure no webhooks. It needs no Issues, Administration,
Secrets, or Environments permissions. Do not reuse the Dashboard Delivery App,
a personal access token, or personal credentials.

The workflow downscopes each short-lived installation token to this repository
and those permissions. Native dispatch uses the separate controller job's
`GITHUB_TOKEN` with `actions: write`, not an Actions-write App token. Reporting
jobs use their own `GITHUB_TOKEN` with `issues: write` for notifications.

**The model token must never be available to a candidate-code executor.** The
analysis job executes only trusted base tooling and handles proposals as data;
it has no delivery credential. The staging/publication jobs use trusted base
tooling and do not execute candidate code. The dispatched package workflow has
read-only contents permission, no model token, no repair App private key/token,
and no protected repair environment. Keep the Arm proxy token confined to the
trusted model step in `smoke-repair-analysis`; do not copy it into package
workflows, publisher jobs, or shared secrets.

## Rollout and Manual Follow-up

1. Keep `SMOKE_REPAIR_ENABLED` unset or `false`. The user runs the offline tests
   and reviews failure handling, policy limits, credential boundaries, and
   proposed workflow changes. Chris then reviews; only a human merges after the
   required checks and approvals. These steps are not waived by green unit tests.
2. Explicitly select and review an action approved for public-repository use or
   an authorized model-call path within Arm-Debug. Neither alternative is
   implemented. Keep repair disabled and retain the fail-closed guard until the
   selected path is implemented and reviewed. Verify the prerequisites above,
   then configure and verify the App installation, exact bot identities, model
   choice, and both environments under the organization's approved pilot or
   routine-operation policy above. Retained required reviewers mean approval
   pauses, even with `SMOKE_REPAIR_ENABLED=true`. No configuration, protection
   removal, or live integration was performed in this documentation change.
3. Approve a bounded live test on reviewed `main`, explicitly enable repair, and
   use the main orchestrator's manual dispatch. Verify real failures, exact
   artifacts, token scopes, candidate execution, and draft ownership end to end.
   Return the flag to `false` after the initial bounded test and review its
   evidence before authorizing routine operation. Do not invent a failure or PR
   merely to claim the integration works.
4. Investigate unsupported or unresolved failures manually using the linked run
   and job evidence. Missing configuration, model refusal, policy rejection,
   native failure, resource limits, or stale identities must not become green.

Native dispatch refuses a pre-existing run for the same workflow, branch, and
candidate SHA. Rerunning only a failed native job can therefore stop with a
manual-investigation report instead of dispatching another test. Staging also
refuses an existing incident branch. Do not repeatedly rerun failed repair jobs
to try to obtain a green result; the recommended recovery is a **new full
main-orchestrator incident** on the current reviewed `main`, with fresh
confirmation evidence and a new repair identity. This is separate from the
one-confirmation-retry limit within each incident.

If `main` advances during orchestration or repair, stale evidence cannot
authorize further dispatch or publication. After merges settle, start a fresh
`workflow_dispatch` on current `main`; rerunning the old run retains its old
SHA. There is no automatic replacement cycle for an ordinary website-only main
advance. A smoke-code merge still triggers its normal new cycle.

Multiple package draft PRs from one incident share the same base SHA. The first
human merge can make the other drafts and their native evidence stale relative
to current `main`. The full new cycle re-evaluates the other failures; they may
no longer need a fix or may need a new incident or manual repair. Do not assume
an old candidate pass authorizes merging every remaining draft, and do not
automatically rebase immutable repair branches to reuse old validation.

Repair does not auto-approve, auto-merge, write `main`, or deploy. Generated-data
review, result publication, and production approval remain separate workflows
with their existing human gates. See [Generated site data review](GENERATED_SITE_DATA_REVIEW.md)
and [Routing and recovery](scripts/README-exact-run-aggregation.md#routing-and-recovery).

Implementation entry points:
[orchestrator](workflows/test-all-packages-orchestrator.yml),
[repair preparation](workflows/smoke-repair.yml),
[package repair jobs](workflows/smoke-repair-package.yml),
[patch policy](scripts/smoke_repair_policy.py), and
[native verification](scripts/smoke_repair_native.py).
