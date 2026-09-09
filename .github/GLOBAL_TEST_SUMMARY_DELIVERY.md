# Global Test Summary delivery

## Purpose

`test-all-packages-summary.yml` assembles the exact results from the 22 bound
Arm64 batch runs. Generation and delivery are separate jobs so package-result
processing never receives a repository write credential.

Publication is valid only when the workflow run itself is bound to
`refs/heads/main`. Both generation base checks and the delivery job reject any
other branch context, even when that branch currently points at the same commit.

The workflow opens or updates a deterministic draft pull request containing
only:

- `data/test-results-index.json`
- direct JSON files under `data/test-results/`

It never approves or merges that pull request, writes the reviewed base branch
directly, changes repository settings, or deploys the dashboard.

## Delivery boundary

1. The generation job has only Actions read and Contents read permissions.
2. After the exact base commit is revalidated, the job packages the complete
   generated path set into one deterministic, bounded JSON artifact. The
   artifact binds the base SHA, canonical path list, file sizes, file digests,
   and exact bytes. The generator exports the exact attempt-specific artifact
   name with its digest; publication consumes that output instead of rebuilding
   a name from its own run-attempt context. A failed-jobs-only rerun therefore
   resolves the artifact created by the original successful generator job.
3. A separate job enters the protected `generated-data-delivery` environment.
   Its built-in `GITHUB_TOKEN` remains Contents read-only.
4. The delivery job checks out the exact base without persisted credentials,
   downloads only the artifact from the same run, independently checks its
   digest and structure, and restores only the allowlisted paths.
5. Only after restoration succeeds does the job mint a short-lived,
   repository-scoped Dashboard Delivery GitHub App token. It immediately
   compares the configured bot login with the minted token's App slug plus
   `[bot]`, then reverifies the path set and every byte before invoking the
   publisher.
6. The publisher accepts that App token only through `GH_TOKEN`, requires
   `credential-source: github-app`, and verifies the existing or new pull
   request author against the configured App bot login.

Missing configuration, a stale base, malformed or extra artifact content,
unexpected workspace changes, a non-main run context, a configured bot that
does not match the minted App, a wrong pull request author, or any byte change
after token minting fails closed before publication.

## Owner configuration

Repository owners must configure these names; never substitute a personal
access token or the built-in workflow token:

- Protected environment: `generated-data-delivery`
- Environment secret: `DASHBOARD_DELIVERY_APP_ID`
- Environment secret: `DASHBOARD_DELIVERY_APP_PRIVATE_KEY`
- Repository variable: `DASHBOARD_DELIVERY_APP_BOT_LOGIN`

The environment should require independent review and prevent self-review. The
Dashboard Delivery App should be installed only on this repository. The token
minted by this workflow is downscoped to Metadata read, Contents write, and Pull
requests write. It receives no Actions, Workflows, Issues, Administration,
Secrets, Environments, or organization permission.

If either environment secret is absent, App-token minting fails. If the bot
login variable is absent, malformed, or names `github-actions[bot]`, the
delivery job stops before checkout and token minting.
