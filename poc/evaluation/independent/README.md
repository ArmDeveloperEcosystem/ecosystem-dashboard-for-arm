# Independent local PoC review evidence

`review.md` records the scoped verdict and remaining limitations. The two HTTP response files preserve the complete final API results, source hashes, per-case assertions, and request timing. `targeted-confirmations.json` records controlled evidence and precision checks. `provider-recall-observations.json` separates observed provider recall from local matching limits without reproducing full external articles.

`regression_cases.json` contains the 38 disclosed and strengthened cases. `fresh_cases.json` contains the eight examples initially held back until the second candidate review; they are now disclosed. Assertions check expected records, known exclusions, identity, and filter behavior. Passing those assertions is not a complete relevance score. Review every returned package and its evidence.

To rerun the HTTP cases, start the local PoC from the repository root using the instructions in `poc/README.md`, then run `run_cases.py` with the PoC Python environment:

```sh
python run_cases.py --cases regression_cases.json --output regression-http-rerun.json
python run_cases.py --cases fresh_cases.json --output fresh-http-rerun.json
```

These commands assume the current directory contains this evidence bundle and the PoC environment is activated. The script locates the repository through `poc/catalog.py`; it requires the Hugo-generated `.poc/public/poc-catalog.json`. The default API is `http://127.0.0.1:8765`. Use `--base-url` for another local port. The default single request worker avoids unnecessarily competing with browser searches for the bounded KB client capacity.

Live KB results can change. Source hashes identify the implementation actually reviewed. The case sets and runner are reproducible evaluation aids, not claims of universal natural-language accuracy or production readiness.
