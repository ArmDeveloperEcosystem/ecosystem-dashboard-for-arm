# Generated-data review publisher

This composite action publishes allowlisted generated files to one
automation-owned draft pull request. It never writes the reviewed base branch
directly.

## Candidate boundary

The caller supplies exact files or directory prefixes through `paths`. Before
creating a commit, the publisher verifies that every Git-visible dirty or
untracked path is inside that allowlist. Existing and newly generated files must
be regular files reached without symlinks. Callers can use
`required-tracked-paths` for exact outputs that must already be tracked regular
files.

The publisher binds generation to one base commit, validates every open pull
request using the deterministic automation head regardless of its current base,
and refuses to update the branch when pull-request or branch ownership is
ambiguous. Branch replacement uses an exact `--force-with-lease` compare-and-swap.

## Deployment gate

A run that creates, updates, preserves, or closes a generated-data draft must
not deploy. After the reviewed pull request is merged, a clean rerun can return
`no_changes` and proceed to deployment.

## External activation blockers

This repository code does not activate governance or deployment protection.
Before production use, repository owners must:

1. Configure live required approving reviews and required checks.
2. Enforce those rules for administrators.
3. Require an authorized repository writer to select
   **Approve workflows to run** for each `GITHUB_TOKEN`-authored pull request.
   A separately governed GitHub App or fine-grained PAT is optional only, not
   required.
4. Configure a protected production environment with required reviewers before
   exposing deployment credentials.
5. Set **Actions > General > Workflow permissions** to the read-only repository
   default. A live default that grants workflow tokens write access remains an
   owner-setting activation blocker. The batch wrappers explicitly cap called
   package jobs to read access, but that code-level cap does not replace the
   repository-level default.

Until those controls are active, the publisher and deployment workflow are
implementation scaffolding, not an enforced production approval boundary.
Do not merge or activate the deployment workflow until repository owners have
explicitly created and protected the `production` environment.
