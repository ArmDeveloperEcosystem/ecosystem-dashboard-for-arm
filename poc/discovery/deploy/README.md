# Internal batch deployment

This package runs one bounded opportunity investigation and writes private Word,
CSV, JSON and SQLite output. It contains **no web server**, public endpoint,
dashboard publishing, source execution, or enabled schedule. The loopback review
UI remains a separate local tool. An authenticated report portal, if wanted,
must use the organization's existing approved access controls.

The supplied systemd units are **opt-in examples for one dedicated internal Linux
host**. They are not installed by tests or CI. Packaging and local validation do
not establish production authorization or live AI acceptance.

## Release inputs and gates

An operational owner must agree the candidate scope, source quotas, private
storage location, report recipients, backup/retention policy, alert destination,
and approved host/network access before enabling a recurring job. Keep the first
deployment manual. Obtain stakeholder acceptance of evidence quality on
representative repositories and image tags.

AI is disabled in the example configuration. Enabling it additionally requires
an approved provider/model, credential, data policy and live acceptance run.
The existing OpenAI adapter is not proof of Azure or Arm-Debug authorization.
For an AI-required acceptance run, override the image arguments with
`--config /config/config.yaml --output-dir /state --catalog /app/content/linux
--fail-on-errors --require-ai`. Preflight fails if AI is disabled or approved
credentials are missing. The run also fails if an eligible fresh finding lacks a
completed, validated advisory review, including a failure or exhausted AI budget.
Reports from any completed investigation remain available for diagnosis. A run
with no eligible fresh findings does not prove live AI behavior; use reviewed
fresh scopes or deliberately refresh a copied acceptance state. Do not present a
deterministic-only run as live AI validation.

The image must pass the organization's image/vulnerability scan before release.
No scanner result is implied by the Dockerfile, dependency hashes or these docs.
Keep the exact image ID/digest, repository revision, reviewed configuration and
validation results with the release record. The packaged catalog is taken from
the same checkout as the code; rebuild deliberately to update that snapshot.

## Build an immutable runtime image

Run from the repository root with Docker BuildKit enabled:

```sh
docker build --platform linux/arm64 \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -f poc/discovery/deploy/Dockerfile \
  -t arm64-opportunity-report:review .
docker image inspect arm64-opportunity-report:review \
  --format '{{.Id}} {{.Architecture}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
```

The Python 3.12.14 Debian Trixie image is pinned to a verified multi-platform
index digest. `requirements.runtime.lock` pins all runtime dependency versions
and approved Linux CPython 3.12 / pure-Python wheel hashes; installation uses
`--require-hashes` and binary wheels only. It supports Linux Arm64 and x86_64.
Dev/test packages are excluded. The Dockerfile's context allowlist excludes
`.git`, `.poc`, credentials, tests and unrelated application files.

Digest/version pinning fixes build inputs; it does not automatically apply
security updates or guarantee a byte-identical image. Review base-image and PyPI
releases, update the digest/version/wheel hashes together, scan the resulting
image and repeat tests. Never accept a new hash simply to bypass a mismatch.
The build-only installer is also hash-pinned, upgraded before installing the
runtime wheels and removed together with Python's bundled installer before the
image is finalized. See [SECURITY.md](SECURITY.md) for dated scanner findings and
any unresolved base-image advisories; a successful build is not security approval.
The primary pilot validation platform is Linux Arm64; validating x86_64 runtime
behavior is a separate check if that platform is used.

## Prepare a private host

Examples assume Docker is `/usr/bin/docker` and a dedicated UID/GID `10001` is
available. Adjust the image's UID consistently if it conflicts with a host user.
Docker daemon access is privileged; use the existing approved host account and
secret-management process. These commands create private host paths; they do not
request new infrastructure or grant additional users Docker access.

```sh
sudo install -d -m 0700 /etc/arm64-opportunities
sudo install -d -m 0700 -o 10001 -g 10001 /var/lib/arm64-opportunities
sudo install -d -m 0755 /usr/local/lib/arm64-opportunities
sudo install -m 0440 -o root -g 10001 poc/discovery/config.example.yaml \
  /etc/arm64-opportunities/config.yaml
sudo install -m 0600 /dev/null /etc/arm64-opportunities/secrets.env
sudo install -m 0755 poc/discovery/deploy/stop-container.sh \
  /usr/local/lib/arm64-opportunities/stop-container.sh
```

Edit `config.yaml` as the host administrator. It must remain readable by container
UID/GID `10001`; root-only mode `0600` would prevent that. Keep `state_path`
omitted so SQLite and report files share `/state`. If overriding it, keep it under
`/state` and retain the same file across every run. The image explicitly passes
the baked catalog through `--catalog`, which takes precedence over configuration.
To use a different catalog snapshot, mount it read-only and override the image
arguments with `--config /config/config.yaml --output-dir /state --catalog
/mounted/catalog --fail-on-errors`. Record the replacement snapshot with the run.

Use a **local persistent filesystem on a single host**, not NFS/SMB/shared storage
or an ephemeral CI cache. SQLite and the process lock coordinate runs on that
host. A bind mount replaces the image's `/state` permissions, so host ownership
must be prepared first. The process uses umask `0077`; state and reports should
not be world-readable. Check existing files when migrating older state.

`secrets.env` may remain empty for unauthenticated public-source checks. If
approved, populate only the dedicated `GITHUB_TOKEN`,
`ARM_DISCOVERY_OPENAI_API_KEY` and `ARM_DISCOVERY_MODEL` values needed by this job.
Never commit the file or copy it into an image. Docker reads this root-owned file
on the host and supplies values to the process. Host Docker administrators can
inspect container environment variables; use only the approved dedicated host.
Generic IDE credentials are not used. Rotate dedicated secrets through the
normal organizational process.

Outbound collection requires HTTPS/DNS to approved source endpoints:
`api.github.com`, `hub.docker.com`, `auth.docker.io` and
`registry-1.docker.io`. The optional current AI adapter additionally calls
`api.openai.com`. Do not add unrestricted inbound access; this job has no listener.

## Manual acceptance run

Replace `sha256:REVIEWED_LOCAL_IMAGE_ID` with the output of `docker image inspect`.
An approved registry image pinned by digest is also valid after explicitly
pulling it. `--pull=never` prevents an unreviewed pull at job start.

```sh
sudo docker run --rm --pull=never --init \
  --read-only --cap-drop=ALL --security-opt=no-new-privileges:true \
  --pids-limit=128 --memory=1g --cpus=2 \
  --tmpfs=/tmp:rw,noexec,nosuid,size=128m,mode=1777 \
  --mount=type=bind,source=/etc/arm64-opportunities/config.yaml,target=/config/config.yaml,readonly \
  --mount=type=bind,source=/var/lib/arm64-opportunities,target=/state \
  --env-file=/etc/arm64-opportunities/secrets.env \
  sha256:REVIEWED_LOCAL_IMAGE_ID
```

The image defaults to `--fail-on-errors`. A failed current collection/AI operation
returns nonzero, retaining any completed report; a legitimate evidence-unknown
finding alone is not an infrastructure failure. Due work that cannot start because
the source allowance is exhausted is an explicit scheduler error; ordinary
partially completed bounded batches and healthy no-work runs remain valid.
Historical failure diagnostics
are retained without making every later healthy run fail. Inspect the run's
outcome and current errors, not just the number of discovered gaps.

Validate the three report files and evidence scope. Repeat the run against the
same state to verify refresh/memory behavior. No fresh work is a valid result:
historical findings stay dated and must not be counted as newly investigated.
Check a failed-source case and alert path before scheduling. Do not delete state
to make repeat runs appear productive.

## Optional weekly scheduling

After manual acceptance, place the immutable image reference in
`/etc/arm64-opportunities/image.env`, mode `0600`, as
`IMAGE=sha256:REVIEWED_LOCAL_IMAGE_ID`. Install the two unit files into
`/etc/systemd/system/`, then run:

```sh
sudo systemctl daemon-reload
sudo systemctl start arm64-opportunity-report.service
sudo systemctl status arm64-opportunity-report.service
sudo journalctl -u arm64-opportunity-report.service --since today
# Only after operational acceptance and an agreed weekly schedule:
sudo systemctl enable --now arm64-opportunity-report.timer
```

The example runs Mondays at 09:00 UTC plus up to 15 minutes of jitter. It has no
catch-up after downtime (`Persistent=false`) and no automatic failure retries.
The oneshot service prevents overlapping timer invocations; the state lock also
rejects another CLI process using that database. A fixed ten-minute outer
deadline terminates a stuck run and its recorded container. This is the hard
wall-clock bound; source/AI budgets and per-read timeouts are additional bounds,
not a guarantee of the same total elapsed time under slow streaming or report
generation. Size that deadline deliberately if reviewed budgets change.

The cleanup helper is idempotent after Docker's normal `--rm` completion and
removes only the container ID created by this service invocation. Test normal
completion, deadline cleanup and host restarts on the actual staging host;
portable script/unit tests cannot establish the host's systemd configuration.

## Operations, recovery and rollback

- **Monitor:** connect service failure, missed weekly completion, disk usage and
  source/model quota alerts to the agreed internal owner. Read `latest.json`
  freshness plus the current-run outcome; a previous successful file can remain
  after a crash. Unknown findings need research, not automatic rerun loops.
- **Partial/failing run:** inspect current errors, preserved observations and
  queued work. Fix access/configuration or wait for a quota reset, then rerun
  manually. Completed observations persist. The next startup marks interrupted
  runs; never overwrite them to conceal failures.
- **Backup:** stop the timer, wait for or stop the service, verify no manual
  process uses the same state, then snapshot the whole state directory including
  SQLite, WAL/SHM files if present, and reports. Use encrypted approved storage.
  Test restoration to a separate directory before relying on backups.
- **Retention:** agree a retention period for generated reports, SQLite evidence
  history and logs. The program does not silently purge history. Review growth
  and storage capacity; archive deliberately. Removing old dated report folders
  does not delete SQLite history. Never delete `latest.json`'s referenced run or
  the database to free space without an approved recovery/migration plan.
- **Update/rollback:** stop the timer and finish the active job, take a backup,
  install the scanned image/config and update `image.env` to its immutable ID.
  Run manually before reenabling the timer. Keep the preceding image and backup.
  To roll back, stop jobs and restore both the old image/config and a compatible
  state backup; do not assume an older image understands a newer database schema.
- **Stop:** `systemctl disable --now arm64-opportunity-report.timer` stops future
  scheduling; `systemctl stop arm64-opportunity-report.service` stops the active
  service and its container. Keep the state for a future restart.

The program drafts opportunities; people decide follow-up, dashboard changes and
maintainer contact. Supported means scoped distribution evidence, not runtime
certification. AI prose remains advisory and needs review even when citations
match collected evidence.

References: [Docker base-image pinning](https://docs.docker.com/build/building/best-practices/#pin-base-image-versions),
[Docker run limits and filesystem options](https://docs.docker.com/reference/cli/docker/container/run/),
[systemd service timeouts](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html),
[systemd timer scheduling](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html).
