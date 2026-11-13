# Conversational search service deployment

The existing dashboard deploys static Hugo output. Conversational search adds a
small Python API behind the **same HTTPS origin**, while the current static-site
deployment and approval gates remain in place. This directory provides an API
image, a validated launcher, a production Hugo overlay and a proxy routing
example. It does not provision infrastructure or change the live dashboard.

```text
Browser: developer.arm.com/ecosystem-dashboard/linux/
  POST /ecosystem-dashboard/api/search
  → existing HTTPS edge: request/rate limits; strips dashboard path prefix
  → private API: Host + Origin checks; bounded admission and body parsing
  → Arm KB /search with server-side credentials, if required
  → exact catalog snapshot built from the same dashboard revision
```

## Existing CloudFront staging

The root-hosted staging site is `https://d1jmgdpytvgwdc.cloudfront.net/`.
The normal website workflow remains manual and feature-disabled. The staging
files below are candidates, not evidence that an API host or route exists.

Start with **Search staging read-only preflight** in GitHub Actions after its PR
is reviewed and merged. Dispatch current `main` and supply the expected backend
account; optionally supply its exact CloudFormation stack and region together.
The existing `production` environment requires an independent reviewer. Its name
is inherited from static delivery; this workflow performs no deployment and does
not change `PRODUCTION_DEPLOYMENT_ENABLED`.

Preflight uses the existing dashboard AWS credentials only for fixed read-only
commands. It checks static distribution/bucket metadata independently of the
expected backend account. Backend discovery stops on an account mismatch; it
never borrows another service's role. Output contains only sanitized status,
counts and configuration matches, not raw accounts, instance IDs, origins, tokens
or AWS error text. Failed checks require resolving the specific access or target
gap; success still does not establish deployment authorization, host capacity,
Python availability, free ports, path ownership or a working HTTPS API route.

Once those facts are verified, build the root-path site and matching catalog:

```sh
hugo --minify --config config.toml,poc/deploy/config.staging.toml \
  --destination .poc/public
```

`arm-dashboard-search.service` and `staging.env.example` describe a separate
Python 3.12 service under `/opt/arm-dashboard-search/current`, with runtime code
in `poc/`, its own `.venv`, and `site/poc-catalog.json` from that same build.
Install dependencies from `poc/requirements.runtime.lock.txt`. Keep releases
root-owned and readable but not writable by the dynamic service user. The root
service manager reads the root-only environment file; credentials belong there
or in the platform's secret injection, never in the public site or release.
Validate the unit with `systemd-analyze verify` on the selected Ubuntu host before
starting it. This change supplies no host installer or shared-service restart.

The proposed route is:

```text
CloudFront POST /api/search
  -> HTTPS certificate-covered origin, origin prefix /dashboard-search
  -> ALB exact /dashboard-search/api/search rule
  -> private nginx listener -> loopback API /api/search
```

Use `nginx.staging.conf.example` inside nginx's `http` context after verifying
ports 8081 and 8080 are unused. Restrict the proxy listener to the load balancer's
security group. Preserve the backend hostname on the TLS hop; the private proxy
sets the application's expected staging Host while retaining the browser Origin.
The target group's private readiness probe uses `/dashboard-search/api/ready`;
do not create a public ALB rule or CloudFront behavior for that path. Existing
TLS, KB and chatbot routes must remain intact.

For the exact CloudFront `/api/search` behavior, disable caching and forward the
body, `Origin`, `Content-Type` and `Sec-Fetch-Site`. CloudFront's all-seven-methods
setting is required to include POST; the proxy enforces POST-only access. Block
bypass of the edge controls and configure viewer rate protection there. The
candidate deliberately does not trust forwarded client IPs: requests share the
API's proxy rate bucket until the actual forwarding chain is verified.

Keep `ARM_SEARCH_SERVE_STATIC=false` and `ARM_SEARCH_DOCS_ENABLED=false`. Set
`ARM_KB_SCOPE_CONFIRMED=true` only for controlled scoped-provider validation;
the supplied environment defaults to false. A ready process otherwise still
returns an explicit unavailable search response. Validate live search through
the external route before publishing the search-enabled static build.

Record the source revision, catalog digest and API/static artifacts as one
release and retain the previous pair for rollback. API activation and CDN
publication are separate operations; do not describe their rollout as atomic.
Recheck the site after invalidation and account for already-open pages during
later releases. Roll back by restoring the last tested pair or publishing the
normal feature-disabled build. The current workflows are not changed to perform
these cloud mutations until the target and access are verified.

## Contract gate

The scoped KB integration was verified on 14 October 2026; relevance and staging
acceptance remain pending. The default `ARM_KB_SCOPE_CONFIRMED=false` blocks KB
search calls and produces an explicit unavailable result. Enable the flag for
controlled validation of the target provider, then repeat scope, package-identity
and representative-query checks before rollout. Enabling the flag alone is not
validation. Follow [the search contract](../README.md).

The image smoke test sets the flag only against a deliberately unreachable
loopback fixture. It expects HTTP 503 with no invented semantic records. Successful
retrieval is exercised separately by the controlled HTTP integration tests.

## Build and run a candidate

Use Python 3.12 and the checksum-verified Hugo extended 0.130.0 version used by
repository CI. Build static output and its matching catalog **from one revision**:

```sh
hugo --config config.toml,poc/deploy/config.production.toml \
  --baseURL https://developer.arm.com/ecosystem-dashboard/ \
  --destination .poc/public
docker build -f poc/deploy/Dockerfile -t arm-dashboard-search:REVIEWED_SHA .
```

Exercise that image locally before staging (requires a running Docker daemon):

```sh
mkdir -p .poc/evaluation
python poc/deploy/smoke.py --image arm-dashboard-search:REVIEWED_SHA \
  --output .poc/evaluation/container-smoke.json
```

The smoke runner starts a temporary API container with a controlled KB outage,
checks the API with a read-only filesystem and production settings, and removes
the container on exit. CI runs this same check and attaches the report;
it does not replace the staging checks below.

Deploy static output through the existing reviewed static-site process. The image
copies only runtime Python modules and the catalog, not package Markdown sources,
credentials, local reports or the full static site. `Dockerfile.dockerignore`
restricts the build context to that allowlist. The official Python multi-platform
base image is pinned to an immutable digest; an organization-approved mirror can
be supplied using `--build-arg PYTHON_IMAGE=...`. Record both the source revision
and resulting image digest, and scan that exact image in the deployment
environment. Review and rescan any update to the base-image digest or dependencies.

Example private listener for the host-local proxy shown in `nginx.conf.example`:

```sh
docker run --rm --name arm-dashboard-search \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --cap-drop ALL --security-opt no-new-privileges \
  --memory 512m --cpus 2 --pids-limit 128 \
  -p 127.0.0.1:8080:8080 \
  -e ARM_SEARCH_PUBLIC_ORIGIN=https://developer.arm.com \
  arm-dashboard-search:REVIEWED_SHA
```

The resource settings are starting limits for staging validation, not measured
capacity guarantees. The container runs as UID/GID 10001, uses one worker, refuses
an externally bound listener without a configured HTTPS origin, and does not
enable proxy-header trust by default. Supply `ARM_KB_API_TOKEN` through the
deployment platform's secret injection if required; never put it in an image,
Hugo parameters or client-side JavaScript.

Without Docker, install `poc/requirements.runtime.lock.txt`, set the same runtime
environment and run:

```sh
python -m poc.serve --host 127.0.0.1 --port 8080
```

## Routing and proxy trust

Merge the example locations into the existing TLS virtual host; do not replace
its certificates, static routes or security configuration. Public requests go to
`/ecosystem-dashboard/api/search`; the proxy forwards `/api/search` privately.
The configured `ARM_SEARCH_PUBLIC_ORIGIN` must exactly match the browser origin.
No cross-origin access is enabled. Requests without Origin are allowed for
non-browser clients and still face body, rate and concurrency limits.

If the application should rate-limit by the original client IP, pass explicit
proxy IPs/CIDRs to the launcher, for example:

```sh
python -m poc.serve --host 0.0.0.0 --port 8080 \
  --proxy-allow-ips 10.0.2.10/32
```

Use the actual proxy address observed by the container; a host proxy may appear
as a container-network gateway. The backend listener must remain inaccessible to
the public. The edge overwrites forwarded headers. Never trust every sender.
Until explicit trust is configured, all requests from a proxy share its service
rate bucket. Each replica has its own bucket, so shared/global limits belong at
the edge. Only one API worker per container is supported by this launch profile.

`--root-path /ecosystem-dashboard` is available where ASGI prefix metadata is
needed; API middleware handles both prefixed and stripped ASGI paths. The normal
proxy rewrite above does not require that option. API-only `/` returns 404; the
static dashboard stays on its established path.

## Runtime limits and health

| Setting | Default | Purpose |
|---|---:|---|
| `ARM_SEARCH_SITE_DIR` | `.poc/public`; image `/app/site` | Immutable matching catalog location |
| `ARM_SEARCH_SERVE_STATIC` | `true`; image `false` | Local full-site host or production API-only |
| `ARM_SEARCH_DOCS_ENABLED` | Local `true`, public/image `false` | Private API documentation opt-in |
| `ARM_SEARCH_MAX_BODY_BYTES` | 8,192 | Actual streamed bytes, including chunked bodies |
| `ARM_SEARCH_BODY_TIMEOUT` | 5 seconds | Total time to receive a request body |
| `ARM_SEARCH_MAX_INFLIGHT` | 8 | Active search requests; overflow receives 503 |
| `ARM_SEARCH_REQUESTS_PER_MINUTE` | 60 per client | Fixed-window limit; overflow receives 429 |
| `ARM_SEARCH_MAX_RATE_CLIENTS` | 4,096 | Bounded client tracking; new clients get 429 when full |
| `ARM_SEARCH_KB_DEADLINE` | 8 seconds | Caller wait for KB; then unavailable response |
| `ARM_SEARCH_KB_MAX_INFLIGHT` | 4 | Active provider work, including timed-out workers |
| `ARM_KB_SCOPE_CONFIRMED` | `false` | Only enable after the scoped provider contract is confirmed and validated |
| `ARM_KB_SEARCH_URL` | `https://knowledge.armdevtechapi.com/search` | Trusted operator-configured endpoint |

Oversized bodies return 413; body timeouts 408; invalid/deep JSON 400; invalid
schema fields 422; wrong content types/encoded bodies 415; cross-origin browser
requests 403. Rate/capacity responses include `Retry-After`. Host checks reject
unconfigured hosts. API responses carry `no-store` and `nosniff`. Response bodies
from the KB are bounded separately at two megabytes and redirects are refused.

`GET /api/health` is liveness; `GET /api/ready` is readiness after a nonempty
catalog is loaded and application startup completes. Readiness does not call the
KB: it reports process readiness only. Health includes the scope configuration and
rollout status; a configured flag still does not prove provider behavior. Send the configured public
Host when probing privately. Never use readiness success as proof that live KB
semantic quality is healthy; monitor unavailable responses and run representative
synthetic search checks separately.

## Observe, recover and release

The launcher emits `arm_search` events to stderr for the platform log collector:
`search_request status=... duration_ms=...`, `search_kb_unavailable`, and
`search_failed exception_type=...`. Aggregate these into request rate, status
counts, latency percentiles, unavailable-response ratio and internal-error rate. Logs omit
queries, bodies, tokens, client IPs and KB URLs; HTTP access logs are disabled.
In-process counters are available at `app.state.metrics` for tests and future
instrumentation; no unauthenticated metrics endpoint is exposed. Configure alerts
in the chosen deployment platform before public rollout.

Shutdown marks the process unready and closes its owned KB worker pool. Admitted
provider work retains its bounded slot until it finishes, even after a caller
deadline. The launcher gives HTTP requests 15 seconds to drain; the supervisor
must enforce a final process-termination grace period (for example 30 seconds)
because DNS/network library work cannot be forcibly interrupted by a Python
thread. Slow streaming responses are checked against the provider deadline after
each network chunk. Repeated outages do not create an unbounded work queue.

First validate the exact static/API revision pair behind staging TLS, including
normal search, outages, limits, real proxy IP handling, browser CSP and observed
latency/memory under the expected load. Agree quality and performance acceptance
thresholds with the owner and retain test evidence. Promote only the reviewed
image and matching static artifact after approval. Roll back by disabling the
Hugo search feature and restoring the last matching static/API revision pair;
existing package-name filtering remains available when the feature is disabled.
