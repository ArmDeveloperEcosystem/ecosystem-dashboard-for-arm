# Generated-data review publisher

This composite action publishes allowlisted generated files to one
automation-owned draft pull request. It never writes the reviewed base branch
directly, approves a workflow, merges a pull request, or deploys content.

## Foundation status

This directory is a behavior-neutral publisher foundation. No existing
production workflow invokes it, and adding it does not change repository
permissions, rules, environments, secrets, or deployment behavior. A later,
separately reviewed integration must supply credentials and wire the action into
an isolated publisher job.

## Candidate boundary

The caller supplies exact files or directory prefixes through `paths`. Before
creating a commit, the publisher verifies that every Git-visible dirty or
untracked path is inside that allowlist. Existing and newly generated files must
be regular files reached without symlinks. Callers can use
`required-tracked-paths` for exact outputs that must already be tracked regular
files and must remain tracked regular files after generation.

The publisher binds generation to one base commit, validates every open pull
request using the deterministic automation head regardless of its current base,
and refuses to update the branch when pull-request or branch ownership is
ambiguous. Branch replacement uses an exact `--force-with-lease` compare-and-swap.

## Credential modes

The action reads the actual API credential from the caller's `GH_TOKEN`
environment variable. It does not accept a token as an action input and does not
mint credentials. Two validated metadata inputs bind the expected PR identity to
the selected credential mode:

- `credential-source: github-token` is the default and requires
  `expected-pr-author-login: github-actions[bot]`.
- `credential-source: github-app` requires the login of the installed App bot,
  such as `arm-ecosystem-publisher[bot]`.

PR author comparisons are case-insensitive because GitHub logins are
case-insensitive. Malformed logins, unknown credential modes, and incompatible
source/author pairs fail closed. Changing credential modes while an existing
deterministic PR is open also fails ownership validation because a PR's author is
immutable.

The PR body records the selected credential mode and expected author. In App
mode it describes only the short-lived GitHub App installation token; it does not
claim that the built-in workflow token created the PR.

## Isolated publisher job

Generation and publication should be separate jobs. The generator should run
with `contents: read`, produce a bounded artifact, and receive no write token.
The publisher job should:

1. Check out the exact reviewed base SHA with persisted checkout credentials
   disabled.
2. Download and validate only the expected generated artifact.
3. Receive one short-lived credential in `GH_TOKEN`.
4. Invoke this action with an exact path allowlist, base SHA, credential source,
   and expected PR author.
5. Expose no deployment credentials and perform no deployment work.

For the built-in token, grant `contents: write` and `pull-requests: write` only to
that publisher job. For a GitHub App, keep the workflow token read-only and scope
the App installation to this repository with only metadata read, contents
read/write, pull requests read/write, and workflows read/write when the generated
allowlist includes `.github/workflows/`. The App-token minting step and every
external action must be pinned to reviewed commit SHAs.

## Review and deployment gate

A run that creates, updates, preserves, or closes a generated-data draft must not
deploy. After the independently reviewed pull request is merged, a clean rerun
against the merged base may return `no_changes`; deployment remains a separate
workflow concern.

Before any future production integration, repository owners must independently
configure required approving reviews, required checks, administrator enforcement,
a read-only default workflow token, and a protected production environment. This
foundation does not activate or satisfy any of those controls.
