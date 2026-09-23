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

## Build and run a candidate

Use Python 3.12 and the checksum-verified Hugo extended 0.130.0 version used by
repository CI. Build static output and its matching catalog **from one revision**:

```sh
hugo --config config.toml,poc/deploy/config.production.toml \
  --baseURL https://developer.arm.com/ecosystem-dashboard/ \
  --destination .poc/public
docker build -f poc/deploy/Dockerfile -t arm-dashboard-search:REVIEWED_SHA .
```

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
| `ARM_SEARCH_KB_DEADLINE` | 8 seconds | Caller wait for KB; then catalog fallback |
| `ARM_SEARCH_KB_MAX_INFLIGHT` | 4 | Active provider work, including timed-out workers |
| `ARM_KB_SEARCH_URL` | `https://knowledge.armdevtechapi.com/search` | Trusted operator-configured endpoint |

Oversized bodies return 413; body timeouts 408; invalid/deep JSON 400; invalid
schema fields 422; wrong content types/encoded bodies 415; cross-origin browser
requests 403. Rate/capacity responses include `Retry-After`. Host checks reject
unconfigured hosts. API responses carry `no-store` and `nosniff`. Response bodies
from the KB are bounded separately at two megabytes and redirects are refused.

`GET /api/health` is liveness; `GET /api/ready` is readiness after a nonempty
catalog is loaded and application startup completes. Readiness does not call the
KB: its outage still permits labeled catalog fallback. Send the configured public
Host when probing privately. Never use readiness success as proof that live KB
semantic quality is healthy; monitor fallback events and run representative
synthetic search checks separately.

## Observe, recover and release

The launcher emits `arm_search` events to stderr for the platform log collector:
`search_request status=... duration_ms=...`, `search_used_catalog_fallback`, and
`search_failed exception_type=...`. Aggregate these into request rate, status
counts, latency percentiles, fallback ratio and internal-error rate. Logs omit
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
