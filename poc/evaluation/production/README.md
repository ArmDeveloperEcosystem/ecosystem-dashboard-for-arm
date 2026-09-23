# Independent production-boundary review evidence

[review.md](review.md) gives the verdict, results and remaining release inputs. All source and catalog digests are in [manifest.json](manifest.json). The recorded catalog was built with `/ecosystem-dashboard/` URLs. A local-root catalog has a different byte digest even when identities and metadata agree.

The review began with 35 withheld, catalog-grounded queries. The first candidate passed 33 assertions but manual all-result review uncovered additional role, attribution and catalog-data defects. Builders corrected those findings; the final candidate passes the strengthened checks. These cases are now disclosed regressions.

From the repository root, build the catalog and run the service as described in `poc/README.md` and `poc/deploy/README.md`. Use the Python environment containing the locked search and test dependencies. Then:

```sh
python poc/evaluation/production/run_heldout.py --base-url http://127.0.0.1:8765 --output heldout-rerun.json
```

The query runner uses `poc/evaluation/independent/run_cases.py` for common identity and assertion checks. An optional `--source-root` points to a frozen source snapshot. Outputs include start/end source hashes; the source must remain unchanged during a run.

For public-origin boundary tests, launch an isolated local profile with `ARM_SEARCH_PUBLIC_ORIGIN=https://dashboard.example`, `ARM_SEARCH_SERVE_STATIC=false`, `ARM_KB_SEARCH_URL=http://127.0.0.1:9`, and port 8771. Then:

```sh
python poc/evaluation/production/run_boundaries.py --base-url http://127.0.0.1:8771 --host dashboard.example --output boundaries-rerun.json
python poc/evaluation/production/run_targeted.py --slow-body-port 8771 --output targeted-rerun.json
```

The targeted runner uses controlled KB passages and the real catalog; the provider-serialization check uses ASGI TestClient, while the slow-body check uses a real TCP connection. The passages are fixtures rather than project support claims.

```sh
python poc/evaluation/production/run_operations.py
```

The operations harness starts local controlled services on ports 8772–8774, exercises admission/rates/log privacy, then terminates its processes. Those ports must be free. It uses a local fake KB and never load-tests the public provider. Its settings deliberately use limits of two to expose boundary behavior; the result is not a production capacity estimate. It writes a fresh operations report and local log samples beside the script.

Recorded data:

- `heldout_cases_original.json`: the fixed original queries and assertions, retained for comparison.
- `heldout_cases.json`: same queries with additional known-false-result exclusions.
- `heldout-final.json`: all final HTTP responses and source hashes.
- `all-result-review.json`: every returned row, catalog role/description and evidence reference.
- `boundary-final.json`, `targeted-final.json`, `operations-final.json`: independent local operational evidence.
- `acceptance-matrix.md`: product, evidence and release criteria used for this review.

Reruns should use new output names to preserve historical evidence. Live KB rankings and availability can change; report fallback modes and inspect every new failure instead of changing expected outcomes to make a run pass.

`main-http-final.json`, `previous38-final.json` and `previous8-final.json` are implementing-agent reruns on the same frozen candidate; their source hashes were checked by the independent reviewer.
