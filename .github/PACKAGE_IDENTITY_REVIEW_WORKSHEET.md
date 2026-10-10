# Package Identity Review Worksheet

This generator creates an advisory, deterministic review worksheet for the
dashboard package corpus. It does not create or approve the production package
identity catalog.

## Safety boundary

- Input must be an exact full lowercase Git commit ID.
- Package pages and workflows are read from that commit's Git objects, not from
  the mutable working tree.
- Frontmatter is parsed with PyYAML's structured safe loader. Generation fails
  clearly when PyYAML is unavailable.
- Malformed frontmatter is recorded as a data-quality flag and contributes no
  identity hints.
- YAML aliases, duplicate keys, excessive nesting, invalid package slugs, and
  orphan package workflows fail closed or are flagged before review.
- Spreadsheet formula-leading cells are prefixed with an apostrophe before CSV
  publication.
- Registry URLs are hints only. They are not evidence or approved identities.
- Raw and validator-normalized candidate spellings are kept in separate columns.
- Candidate spellings that cannot satisfy the validator are isolated in an
  invalid-hints column and cannot be copied into approved identities unnoticed.
- Every pip and npm decision starts as `unknown`, `exhaustive=false`, with no
  reviewer, review time, rationale, or approved identity.
- The evidence ledger starts empty.
- The generator never emits `verified` or `not_applicable` decisions.

## Generate a worksheet

From the repository root:

```bash
REVISION="$(git rev-parse HEAD)"
python3 -I -B build_steps/generate_package_identity_review_worksheet.py \
  --revision "$REVISION" \
  --output-directory /tmp/package-identity-review
```

The output directory contains:

- `corpus-inventory.csv`: exact page/workflow paths, presence, hashes,
  structured metadata hints, and data-quality flags;
- `registry-decisions.csv`: one unresolved pip row and one unresolved npm row
  for every package page;
- `evidence-ledger.csv`: an empty evidence template for qualified reviewers;
  and
- `manifest.json`: the exact base commit, row counts, safety declarations, and
  SHA-256 hashes of all CSV files.

Generation requires a new output-directory path and publishes the complete
directory with one rename, preventing mixed files from separate runs.

These files are review inputs. A separate reviewed process must resolve
registry identities, collect immutable registry evidence, and create the
canonical `.github/package-identity-catalog.json`.

Each decision row maps to one catalog `registries.pip` or `registries.npm`
dimension. `decision_status`, `exhaustive`, and `approved_identities` become the
dimension fields only after review. Evidence rows carry the exact validator
fields `source_kind`, `source_locator`, `source_revision`, `evidence_sha256`,
`rationale`, `verified_by`, and `verified_at`; `base_commit`, `slug`, `registry`,
and `decision_id` bind each row back to its reviewed package dimension.

## Test

```bash
python3 -I -B tests/test_package_identity_review_worksheet.py -v
```
