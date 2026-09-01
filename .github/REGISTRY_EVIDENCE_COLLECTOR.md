# Registry Evidence Collector

`build_steps/collect_registry_evidence.py` collects bounded PyPI or npm API
snapshots for explicit candidate identities already present in an exact package
identity worksheet. It is advisory tooling, not an approval system.

## Trust boundary

- The collector verifies the worksheet manifest and all three worksheet file
  sizes and SHA-256 digests before making a request.
- Every request requires an explicit `--candidate DECISION_ID=IDENTITY` argument.
  The normalized identity must already be present in that decision's immutable
  worksheet hints.
- The collector constructs the URL itself. The only accepted endpoints are
  `https://pypi.org/pypi/<name>/json` and
  `https://registry.npmjs.org/<name>/latest`.
- Redirects, URL credentials, ports, query strings, fragments, proxies,
  compressed responses, non-JSON media types, oversized responses, identity
  mismatches, duplicate JSON keys, and excessive JSON complexity fail closed.
- The network timeout is bounded to 0.1 through 30 seconds and defaults to 10
  seconds. No OpenAI token, registry credential, cookie, or delivery credential
  is read or sent.
- Registry JSON is canonicalized before hashing. The lowercase SHA-256 is used
  as both the immutable evidence revision and evidence digest.
- The collector never reads workflow shell and never uses AI.

## Run

Use Python isolated mode and a new output path:

```bash
python3 -I -B build_steps/collect_registry_evidence.py \
  --worksheet-directory /tmp/package-identity-review \
  --output-directory /tmp/package-identity-evidence \
  --candidate 'orjson:pip=orjson'
```

The output contains canonical snapshots, `collected-evidence.csv`,
`proposed-decisions.csv`, and `collector-manifest.json`. Proposals always remain
`unknown`, `exhaustive=false`, with no approved identity. Evidence reviewer and
review time fields remain empty. A qualified human must inspect the snapshot,
complete those fields, and decide whether wider evidence supports a verified,
ambiguous, unknown, or exhaustive decision. A successful lookup never causes
the collector to claim `not_applicable` or exhaustive coverage.

## Test

```bash
python3 -I -B tests/test_registry_evidence_collector.py -v
```
