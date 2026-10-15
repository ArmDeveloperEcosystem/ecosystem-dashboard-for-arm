# Package Identity Catalog Compiler

The compiler converts a completely reviewed worksheet bundle into the canonical
schema `1.1` catalog. It does not research identities, fetch evidence, fill
review fields, or infer decisions.

## Reviewed bundle

Start with all four files emitted by the worksheet generator. Keep
`manifest.json` and `corpus-inventory.csv` unchanged. Reviewers may edit only
these fields in `registry-decisions.csv`:

- `decision_status`: `verified`, `not_applicable`, `unknown`, or `ambiguous`;
- `exhaustive`: lowercase `true` or `false`;
- `approved_identities`: a compact JSON array such as `["requests"]` or `[]`;
- `review_state`: exactly `reviewed`; and
- `review_notes`: optional single-line reviewer context.

Add one to 32 rows per decision to `evidence-ledger.csv`. Every evidence row
must retain the generator base commit and exact `decision_id`, `slug`, and
registry join. Fill every validator evidence field. Leave `rationale` empty
only when schema `1.1` permits it.

Do not retain a spreadsheet-added leading apostrophe in reviewed fields. For
example, enter an npm identity as `@scope/package` inside the JSON array, not
`'@scope/package`. The compiler rejects formula-neutralized reviewer input
rather than guessing the intended value.

## Compile

Run from the exact commit recorded in the generator manifest:

```bash
python3 -I -B build_steps/compile_package_identity_catalog.py \
  --worksheet-directory /path/to/reviewed-package-identity-worksheet
```

The compiler:

1. regenerates the pristine worksheet from the manifest commit;
2. verifies the exact manifest and every declared generator hash;
3. requires the inventory to remain byte-identical;
4. permits changes only in the five reviewable decision columns;
5. verifies complete pip/npm decisions, evidence joins, and canonical ordering;
6. builds schema `1.1` without inferring any field;
7. runs the existing validator in a temporary detached worktree; and
8. atomically writes `.github/package-identity-catalog.json` only after all
   checks pass.

The compiler does not run Hugo. The required `Package identity catalog
merge-tree` pull-request check performs the final immutable revision and pinned
Hugo `0.130.0` validation.

## Test

```bash
python3 -I -B tests/test_package_identity_catalog_compiler.py -v
```
