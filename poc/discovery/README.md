# Internal Linux Arm64 support-gap discovery

This bounded PoC collects GitHub release metadata from selected project repositories and Docker Hub tag/OCI platform metadata, persists investigation history in SQLite, and produces a Word review report, JSON evidence, and CSV findings. Evidence is authoritative for the selected repository; upstream project ownership is not independently verified. It inspects metadata only: it does not run downloaded code, install projects, pull image layers, change the public dashboard, publish findings, or contact maintainers.

```sh
.venv/bin/python -m poc.discovery \
  --config poc/discovery/config.example.yaml \
  --output-dir .poc/discovery \
  --catalog .poc/public/poc-catalog.json
```

No credentials are required for public metadata. `GITHUB_TOKEN` optionally increases the available GitHub API allowance. Rate limits and other HTTP failures are reported as incomplete evidence. Source requests only reach an explicit official-host allowlist; redirects are disabled to prevent credential forwarding. Each response has a byte limit and every run has request, candidate, pagination, and time caps. API errors are not retried within a run; the persisted unknown result becomes due on the configured shorter refresh interval. This keeps rate-limited retries bounded.

The default seeds demonstrate Linux Arm64 distribution support, missing/unclear release evidence, and a potential tag-specific gap (`library/mysql:5.7`, a selected legacy distribution; this is **not** a claim that current MySQL or all versions lack Arm64 support). A small star-ranked GitHub search discovers additional repositories using a configured topic and language. Docker Hub discovery is limited to the selected image/tag seeds in this PoC. The selected repository release is the first non-draft, non-prerelease returned by GitHub API order, not a promise of the newest semantic version. Release assets use their own paginated endpoint; the embedded release asset array is never assumed complete.

## Contract

```python
from poc.discovery import run_pipeline

summary = run_pipeline(config_path, output_dir, catalog_path=None)
```

Each run writes `OUTPUT/RUN_ID/opportunities.{docx,json,csv}` and atomically updates `OUTPUT/latest.json`. The returned dictionary contains `run_id`, `generated_at`, `counts`, `findings`, `retained_findings`, `failures`, `skipped`, `limits`, `refresh_hours`, `saved_history`, `ai_review`, `report_paths`, and `state_path`. Each finding contains `candidate_id`, `source`, `name`, `status` (`supported`, `gap`, `unknown`), exact `scope`, `reason`, linked `evidence`, `catalog_tracked` (true/false/null), `investigated_before`, `checked_at`, `next_check_at`, `recommended_action`, and optional advisory `ai_review`.

`findings` and status/investigation counts describe only this run. `retained_findings` contains the full most recent observation for every previously investigated candidate not rechecked in this run, with `historical: true` and the original dates, status, scope, and evidence. UIs may merge these arrays while visibly labeling historical results and their `checked_at` age. They must not count retained findings as newly investigated or freshly verified. `saved_history` provides a compact current-state index including `evidence_url`, observed/due dates, scope, and investigation count. Word reports include this linked history; CSV describes only this run's findings.

SQLite stores all candidates (including capped/deferred work), every completed observation, evidence fingerprints, refresh due dates, and run summaries. Repeating a run before its due date preserves the finding and does not reinvestigate it. `force_refresh: true` performs an explicit recheck and labels it as refreshed. Previously queued candidates remain queued even if omitted from a later seed configuration: use a separate output/state path to establish a separate investigation scope. An expiring database lease prevents concurrent runs on the same state file.

This is a small internal pilot: history is retained without automatic archival and loaded into memory for reporting. Production operation needs retention/archival policy, paged history views, and operational ownership.

Catalog comparison extracts GitHub and Docker Hub repository identities from URLs in the supplied catalog JSON/YAML, including nested package metadata. Exact repository aliases can be recorded with `github_repo`/`github_repository` keys. It never uses title similarity to infer identity. Catalog membership is orthogonal to support: cataloged projects are still assessed and may have a specific release/tag gap. No URL match means no match was found, not proof the project is absent from all internal tracking.

## Evidence policy

| Evidence | Outcome |
| --- | --- |
| Uploaded artifact from the selected repository explicitly names Linux and Arm64/aarch64 | Supported for at least that advertised artifact; no claim about all components or runtime certification |
| Complete, unambiguous release inventory contains other Linux architecture binaries and no Linux Arm64 artifact | Gap for that exact release's published binary set |
| Complete runtime tag/index/config inventory excludes Linux Arm64 | Gap for that exact tag |
| Incomplete pagination, API failure, unknown platform fields, ambiguous filenames, no relevant binary releases | Unknown; never treated as unsupported |

Darwin/Windows Arm64 and Armv7 are excluded from Linux Arm64 support. A single-platform OCI manifest requires its referenced config blob to determine architecture and OS. Unknown/unknown descriptors are only ignored as attestations when the OCI descriptor explicitly labels them as such. Readmes are pinned to the selected release tag where available, and retained as context; keyword occurrences alone do not decide status. Positive evidence can establish a supported artifact even when unrelated inventory/context collection is incomplete, with the collection issue retained.

## Optional AI interpretation

AI review is disabled by default and reported as `not_configured`; deterministic collection/classification is fully usable without an AI service. Enable `ai_review.enabled`, set `OPENAI_API_KEY`, and set `OPENAI_MODEL` (or `ai_review.model`) to a Responses API model supporting structured output. The configured adapter makes bounded requests to `https://api.openai.com/v1/responses` using `store: false`. Only bounded public evidence excerpts and scope/status are supplied. No catalog records, credentials, or private state are included.

The model returns an advisory note plus exact quotations and source URLs. Every quote must be a substring of the collected excerpt and every URL must match its source; otherwise the review is rejected. Quotes validate traceability, **not** the semantic correctness of every generated sentence, so human review remains required. AI cannot change deterministic classification. Missing credentials/model, refusals, malformed output, budget exhaustion and invalid citations are explicitly reported. For tests/other providers, `run_pipeline(..., reviewer=callable)` accepts the same small review contract.

AI calls have a separate call/token/time budget. The overall discovery wall-clock cap is checked before each next candidate; one configured AI review or network read can consume its remaining per-call timeout before returning. Word/JSON rendering is outside the network time cap.

## Verification and report QA

```sh
.venv/bin/python -m pytest poc/tests/test_discovery*.py -q
```

The tests exercise positive/negative/unknown scopes, incomplete pagination, failure retention, OS/architecture exclusion, single-platform config requirements, request limits, persistent memory, refresh/idempotence, queue retention, and AI citation validation. The generated Word report uses Letter pages, explicit business-brief styles, fixed-width tables, linked citations, and saved-history/limitations sections. Before distributing a report, render it with the documents skill's `render_docx.py` and visually inspect every page. The generator does not claim visual QA was completed automatically.

Official API references: [GitHub release assets](https://docs.github.com/en/rest/releases/assets#list-release-assets), [GitHub release listing](https://docs.github.com/en/rest/releases/releases#list-releases), [GitHub repository search](https://docs.github.com/en/rest/search/search#search-repositories), [Docker Hub tag API](https://docs.docker.com/reference/api/hub/latest/operations/GetRepositoryTag/), [OCI image index](https://github.com/opencontainers/image-spec/blob/main/image-index.md), [OCI image configuration](https://github.com/opencontainers/image-spec/blob/main/config.md), and [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
